"""A scripted LLM so the graphs can be tested without a network or an API key."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class FakeLLM:
    """Returns pre-scripted responses, keyed by the schema being requested.

    Dispatching on schema rather than call order keeps tests readable: a test
    says "here are the question batches, here are the drafts" without having to
    know the exact order the graph interleaves them.
    """

    def __init__(self, responses: dict[type[BaseModel], list[BaseModel]]) -> None:
        self._queues = {schema: list(items) for schema, items in responses.items()}
        self.calls: list[tuple[type[BaseModel], str]] = []

    def structured(
        self, schema: type[T], system: str, user: str, role: str = "default"
    ) -> T:
        self.calls.append((schema, user))
        queue = self._queues.get(schema)
        if not queue:
            raise AssertionError(
                f"FakeLLM has no scripted response left for {schema.__name__}. "
                f"Calls so far: {[c[0].__name__ for c in self.calls]}"
            )
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def count(self, schema: type[BaseModel]) -> int:
        return sum(1 for s, _ in self.calls if s is schema)
