"""The LLM layer.

Everything that needs judgement goes through this narrow interface: ask a model
for an instance of a Pydantic schema, get one back or raise. Keeping it small
means the interview, the semantic lint, gap research and the self-review all
share one path for retries, schema repair, prompt trimming and rate pacing.

Two providers are supported. Groq is the default because it is what this project
runs on; Anthropic is kept because the prompts were written against it and it is
the better critic when a key is available. Selection is by environment, never
hardcoded at a call site.
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ouroboros.llm.budget import (
    ANTHROPIC_LIMITS,
    GROQ_LIMITS,
    ProviderLimits,
    TokenRateLimiter,
    estimate_tokens,
    trim_to_tokens,
)

T = TypeVar("T", bound=BaseModel)


def _load_env() -> None:
    """Read a .env from the project root so keys never live in shell history."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv is a convenience, not a requirement
        return
    for parent in [Path.cwd(), *Path(__file__).resolve().parents]:
        candidate = parent / ".env"
        if candidate.exists():
            load_dotenv(candidate, override=False)
            return


_load_env()


# The Groq ids were verified against the live model list rather than assumed:
# of the models this account can reach, only the gpt-oss family produces
# reliable structured output — the Qwen models fail tool calling outright.
PROVIDER_MODELS = {
    "groq": {
        "default": "openai/gpt-oss-120b",
        "critic": "openai/gpt-oss-120b",
        "fast": "openai/gpt-oss-20b",
    },
    "anthropic": {
        "default": "claude-sonnet-5",
        "critic": "claude-opus-5",
        "fast": "claude-haiku-4-5-20251001",
    },
}

PROVIDER_LIMITS = {"groq": GROQ_LIMITS, "anthropic": ANTHROPIC_LIMITS}

# How each provider is asked for structured output. Measured, not assumed:
# on Groq, LangChain's default function-calling path fails on schemas the size
# of SpecDraft ("attempted to call too many tools" / "did not call a tool"),
# while json_schema returns them reliably. Anthropic's tool calling is fine, so
# it keeps the library default.
STRUCTURED_METHOD: dict[str, str | None] = {"groq": "json_schema", "anthropic": None}

RATE_LIMIT_RETRIES = 4

# One limiter per provider: the quota is per account, not per model instance.
_LIMITERS: dict[str, TokenRateLimiter] = {}


def limiter_for(provider: str) -> TokenRateLimiter:
    if provider not in _LIMITERS:
        _LIMITERS[provider] = TokenRateLimiter(
            PROVIDER_LIMITS[provider].tokens_per_minute
        )
    return _LIMITERS[provider]


class LLM(Protocol):
    """Returns an instance of `schema`, or raises."""

    def structured(
        self, schema: type[T], system: str, user: str, role: str = "default"
    ) -> T: ...


def active_provider() -> str:
    """Groq when its key is present, Anthropic otherwise. Env wins over both."""
    explicit = os.environ.get("OUROBOROS_LLM_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in PROVIDER_MODELS:
            raise RuntimeError(
                f"OUROBOROS_LLM_PROVIDER is '{explicit}'; expected one of "
                f"{', '.join(sorted(PROVIDER_MODELS))}."
            )
        return explicit
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "groq"


def model_for(role: str = "default", provider: str | None = None) -> str:
    provider = provider or active_provider()
    override = os.environ.get(f"OUROBOROS_{role.upper()}_MODEL")
    return override or PROVIDER_MODELS[provider][role]


def limits_for(provider: str | None = None) -> ProviderLimits:
    return PROVIDER_LIMITS[provider or active_provider()]


def salvage_failed_generation(schema: type[T], error: Exception) -> T | None:
    """Recover a valid object from a rejected generation.

    When a provider refuses a response because the model wrote JSON instead of
    calling a tool, it returns that JSON in `failed_generation`. The work is
    already paid for and is often perfectly valid, so parse it rather than
    spending another request to ask again.
    """
    text = str(error)
    marker = "'failed_generation': "
    if marker not in text:
        return None

    fragment = text[text.index(marker) + len(marker):]
    start = fragment.find("{")
    if start == -1:
        return None

    # Walk the braces to find the end of the embedded JSON document.
    depth, in_string, escaped = 0, False, False
    for index, character in enumerate(fragment[start:], start=start):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
        elif character == '"':
            in_string = not in_string
        elif not in_string:
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    candidate = fragment[start : index + 1]
                    try:
                        return schema.model_validate_json(candidate)
                    except Exception:  # noqa: BLE001 - salvage is best-effort
                        try:
                            import ast

                            return schema.model_validate_json(
                                ast.literal_eval(f"'''{candidate}'''")
                            )
                        except Exception:  # noqa: BLE001
                            return None
    return None


def _is_rate_limit(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "rate limit" in text
        or "rate_limit" in text
        or "429" in text
        or "413" in text
        or "too many requests" in text
        or "request too large" in text
    )


class StructuredChat:
    """Shared budgeting, pacing, retry and validation over any chat model.

    Four failure modes are handled here so no caller has to think about them:
    a prompt larger than the provider will accept (trimmed), a per-minute quota
    (paced), a transient rate limit (backed off), and a schema violation
    (retried once with the error fed back, which fixes the usual cause — a
    dropped required field rather than a misunderstood task).
    """

    def __init__(self, model: str, provider: str, temperature: float = 0.0):
        self.model = model
        self.provider = provider
        self.temperature = temperature
        self.limits = PROVIDER_LIMITS[provider]
        self.limiter = limiter_for(provider)
        self.trimmed_prompts = 0
        self.salvaged = 0
        self._clients: dict[int, object] = {}

    def _build(self, max_output_tokens: int):  # pragma: no cover
        raise NotImplementedError

    def _client(self, max_output_tokens: int):
        if max_output_tokens not in self._clients:
            self._clients[max_output_tokens] = self._build(max_output_tokens)
        return self._clients[max_output_tokens]

    def structured(
        self, schema: type[T], system: str, user: str, role: str = "default"
    ) -> T:
        from langchain_core.messages import HumanMessage, SystemMessage

        max_output = self.limits.output_for(role)
        prompt_budget = self.limits.prompt_budget(role) - estimate_tokens(system)
        user, was_trimmed = trim_to_tokens(user, max(256, prompt_budget))
        if was_trimmed:
            self.trimmed_prompts += 1

        method = STRUCTURED_METHOD.get(self.provider)
        client = self._client(max_output)
        model = (
            client.with_structured_output(schema, method=method)
            if method
            else client.with_structured_output(schema)
        )

        def invoke(prompt: str) -> T:
            cost = estimate_tokens(system) + estimate_tokens(prompt) + max_output
            last: Exception | None = None

            for attempt in range(RATE_LIMIT_RETRIES):
                self.limiter.acquire(cost)
                try:
                    return model.invoke(
                        [SystemMessage(content=system), HumanMessage(content=prompt)]
                    )
                except Exception as error:  # noqa: BLE001 - inspected below
                    last = error

                    # The model may have produced exactly what we asked for and
                    # merely delivered it the wrong way. Take it.
                    recovered = salvage_failed_generation(schema, error)
                    if recovered is not None:
                        self.salvaged += 1
                        return recovered

                    if not _is_rate_limit(error) or attempt == RATE_LIMIT_RETRIES - 1:
                        raise
                    # The quota resets on a rolling minute; wait it out.
                    time.sleep(min(2**attempt * 8, 60) + random.uniform(0, 2))
            raise last  # pragma: no cover - loop returns or raises

        try:
            return invoke(user)
        except Exception as first_error:  # noqa: BLE001 - repaired below
            if _is_rate_limit(first_error):
                raise
            repair_note = (
                "\n\nYour previous response could not be parsed into the required "
                f"schema. The error was:\n{str(first_error)[:600]}\n"
                "Return a response that satisfies every required field."
            )
            repaired, _ = trim_to_tokens(
                user, max(256, prompt_budget - estimate_tokens(repair_note))
            )
            return invoke(repaired + repair_note)


class GroqLLM(StructuredChat):
    def __init__(self, model: str, temperature: float = 0.0):
        super().__init__(model=model, provider="groq", temperature=temperature)

    def _build(self, max_output_tokens: int):
        from langchain_groq import ChatGroq

        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError(
                "GROQ_API_KEY is not set. Put it in a .env file at the project root "
                "or export it before starting the server."
            )
        return ChatGroq(
            model=self.model,
            temperature=self.temperature,
            max_tokens=max_output_tokens,
        )


class AnthropicLLM(StructuredChat):
    def __init__(self, model: str, temperature: float = 0.0):
        super().__init__(model=model, provider="anthropic", temperature=temperature)

    def _build(self, max_output_tokens: int):
        from langchain_anthropic import ChatAnthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Put it in a .env file at the project "
                "root or export it before starting the server."
            )
        return ChatAnthropic(
            model=self.model,
            temperature=self.temperature,
            max_tokens=max_output_tokens,
        )


def build_llm(role: str = "default", provider: str | None = None) -> LLM:
    provider = provider or active_provider()
    model = model_for(role, provider)
    implementation = GroqLLM if provider == "groq" else AnthropicLLM
    return implementation(model=model)


def default_llm() -> LLM:
    return build_llm("default")


def critic_llm() -> LLM:
    return build_llm("critic")


def context_chars(role: str = "default", provider: str | None = None) -> int:
    """How much retrieved context a prompt for this role can afford.

    Callers use it to size corpus excerpts, so the same code stays rich on
    Anthropic and stays inside the free tier on Groq.
    """
    from ouroboros.llm.budget import tokens_to_chars

    limits = limits_for(provider)
    # Roughly half the prompt budget goes to retrieved context; the rest is the
    # spec, the draft, and the instructions.
    return max(800, tokens_to_chars(int(limits.prompt_budget(role) * 0.45)))


def describe_configuration() -> dict[str, object]:
    """What the server reports at /api/health, so misconfiguration is visible."""
    provider = active_provider()
    key_var = "GROQ_API_KEY" if provider == "groq" else "ANTHROPIC_API_KEY"
    limits = limits_for(provider)
    return {
        "provider": provider,
        "model": model_for("default", provider),
        "critic_model": model_for("critic", provider),
        "api_key_present": bool(os.environ.get(key_var)),
        "tokens_per_minute": limits.tokens_per_minute,
    }
