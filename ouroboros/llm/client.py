"""The LLM layer.

Everything that needs judgement goes through this narrow interface: ask a model
for an instance of a Pydantic schema, get one back or raise. Keeping it small
means the interview, the semantic lint, gap research and the self-review all
share one path for retries, schema repair, prompt trimming and rate pacing.

Three providers are supported: OpenAI, Groq and Anthropic. Selection is by
environment, never hardcoded at a call site, so the same code runs against a
generous paid quota or a tight free tier without changes elsewhere.
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
    OPENAI_LIMITS,
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
    "openai": {
        "default": "gpt-4o-mini",
        "critic": "gpt-4o-mini",
        "fast": "gpt-4o-mini",
    },
    "anthropic": {
        "default": "claude-sonnet-5",
        "critic": "claude-opus-5",
        "fast": "claude-haiku-4-5-20251001",
    },
}

PROVIDER_LIMITS = {
    "groq": GROQ_LIMITS,
    "openai": OPENAI_LIMITS,
    "anthropic": ANTHROPIC_LIMITS,
}

# How each provider is asked for structured output, in fallback order. Measured,
# not assumed: on Groq, LangChain's default function-calling path fails on
# schemas the size of SpecDraft ("attempted to call too many tools" / "did not
# call a tool"), while json_schema returns them reliably — but json_schema has
# its own failure mode where the model echoes the schema back. The two fail
# differently, so trying the second when the first breaks recovers a run that
# would otherwise be lost. Anthropic's tool calling is fine and keeps the
# library default.
STRUCTURED_METHODS: dict[str, list[str | None]] = {
    "groq": ["json_schema", "function_calling"],
    "openai": ["json_schema", "function_calling"],
    "anthropic": [None],
}

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
    """First provider with a key present. An explicit setting wins over all."""
    explicit = os.environ.get("OUROBOROS_LLM_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in PROVIDER_MODELS:
            raise RuntimeError(
                f"OUROBOROS_LLM_PROVIDER is '{explicit}'; expected one of "
                f"{', '.join(sorted(PROVIDER_MODELS))}."
            )
        return explicit
    for provider, key in (
        ("openai", "OPENAI_API_KEY"),
        ("groq", "GROQ_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    ):
        if os.environ.get(key):
            return provider
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


class DailyQuotaExhausted(RuntimeError):
    """The provider's per-day token allowance is gone.

    Distinct from a per-minute limit on purpose: waiting a minute fixes one and
    does nothing for the other, so retrying a daily limit just burns time and
    then fails anyway.
    """


def _is_daily_limit(error: Exception) -> bool:
    text = str(error).lower()
    return "per day" in text or "tpd" in text


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
        self.method_fallbacks = 0
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

        client = self._client(max_output)
        methods = STRUCTURED_METHODS.get(self.provider, [None])

        def bind(method: str | None):
            return (
                client.with_structured_output(schema, method=method)
                if method
                else client.with_structured_output(schema)
            )

        model = bind(methods[0])

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

                    if _is_daily_limit(error):
                        raise DailyQuotaExhausted(
                            f"{self.provider} has no tokens left for today. Waiting "
                            "will not help; use a different key or provider, or "
                            "resume tomorrow. Any completed interview is still in "
                            f"the session.\n\nProvider said: {str(error)[:300]}"
                        ) from None

                    if not _is_rate_limit(error) or attempt == RATE_LIMIT_RETRIES - 1:
                        raise
                    # The quota resets on a rolling minute; wait it out.
                    time.sleep(min(2**attempt * 8, 60) + random.uniform(0, 2))
            raise last  # pragma: no cover - loop returns or raises

        try:
            return invoke(user)
        except Exception as first_error:  # noqa: BLE001 - recovered below
            if _is_rate_limit(first_error):
                raise

            # Same prompt, different way of asking. The methods fail on
            # different inputs, so this is a cheaper recovery than re-prompting.
            for fallback in methods[1:]:
                try:
                    model = bind(fallback)
                    result = invoke(user)
                    self.method_fallbacks += 1
                    return result
                except Exception as fallback_error:  # noqa: BLE001
                    if _is_rate_limit(fallback_error):
                        raise
                    first_error = fallback_error

            model = bind(methods[0])
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


class OpenAILLM(StructuredChat):
    def __init__(self, model: str, temperature: float = 0.0):
        super().__init__(model=model, provider="openai", temperature=temperature)

    def _build(self, max_output_tokens: int):
        from langchain_openai import ChatOpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Put it in a .env file at the project "
                "root or export it before starting the server."
            )
        return ChatOpenAI(
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


IMPLEMENTATIONS = {"groq": GroqLLM, "openai": OpenAILLM, "anthropic": AnthropicLLM}


def build_llm(role: str = "default", provider: str | None = None) -> LLM:
    provider = provider or active_provider()
    return IMPLEMENTATIONS[provider](model=model_for(role, provider))


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
    key_var = {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }[provider]
    limits = limits_for(provider)
    return {
        "provider": provider,
        "model": model_for("default", provider),
        "critic_model": model_for("critic", provider),
        "api_key_present": bool(os.environ.get(key_var)),
        "tokens_per_minute": limits.tokens_per_minute,
    }
