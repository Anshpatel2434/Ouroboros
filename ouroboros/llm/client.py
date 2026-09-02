"""The LLM layer.

Everything that needs judgement goes through this narrow interface: ask a model
for an instance of a Pydantic schema, get one back or raise. Keeping it this
small means the interview, the semantic lint, gap research and the self-review
all share one retry/validation path, and tests can substitute a fake without
touching a network.
"""

from __future__ import annotations

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Interviewing and generation are long-context, judgement-heavy but not
# adversarial; the critic pass benefits from the stronger model.
DEFAULT_MODEL = "claude-sonnet-5"
CRITIC_MODEL = "claude-opus-5"


class LLM(Protocol):
    """Returns an instance of `schema`, or raises."""

    def structured(self, schema: type[T], system: str, user: str) -> T: ...


class AnthropicLLM:
    """Structured-output wrapper over ChatAnthropic.

    Schema validation failures are retried once with the error fed back, which
    is the cheapest fix for the usual cause: a model that dropped a required
    field rather than one that misunderstood the task.
    """

    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature
        self._client = None

    def _chat(self):
        if self._client is None:
            from langchain_anthropic import ChatAnthropic

            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set. Ouroboros needs it to run the "
                    "interview, the semantic lint, and the self-review."
                )
            self._client = ChatAnthropic(
                model=self.model, temperature=self.temperature, max_tokens=8192
            )
        return self._client

    def structured(self, schema: type[T], system: str, user: str) -> T:
        from langchain_core.messages import HumanMessage, SystemMessage

        model = self._chat().with_structured_output(schema)
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        try:
            return model.invoke(messages)
        except Exception as first_error:  # noqa: BLE001 - retried below
            repair = (
                f"{user}\n\nYour previous response could not be parsed into the "
                f"required schema. The error was:\n{first_error}\n"
                "Return a response that satisfies every required field."
            )
            return model.invoke([SystemMessage(content=system), HumanMessage(content=repair)])


def default_llm() -> LLM:
    return AnthropicLLM()


def critic_llm() -> LLM:
    return AnthropicLLM(model=CRITIC_MODEL)
