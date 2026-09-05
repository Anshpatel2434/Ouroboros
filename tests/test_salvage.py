"""Recovering a valid object from a rejected generation.

Groq rejects a response when the model writes JSON instead of calling a tool,
but returns that JSON in `failed_generation`. It is usually correct and always
already paid for, so it is parsed rather than re-requested.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ouroboros.llm.client import salvage_failed_generation


class Person(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)


def groq_error(payload: str) -> Exception:
    return Exception(
        "Error code: 400 - {'error': {'message': 'Tool choice is required, but "
        "model did not call a tool', 'type': 'invalid_request_error', 'code': "
        f"'tool_use_failed', 'failed_generation': '{payload}'}}}}"
    )


def test_salvages_a_valid_payload():
    recovered = salvage_failed_generation(
        Person, groq_error('{"name": "noteseek", "tags": ["cli", "search"]}')
    )
    assert recovered is not None
    assert recovered.name == "noteseek"
    assert recovered.tags == ["cli", "search"]


def test_salvages_a_payload_containing_nested_braces():
    payload = '{"name": "x", "tags": ["{not json}", "b"]}'
    recovered = salvage_failed_generation(Person, groq_error(payload))
    assert recovered is not None
    assert recovered.tags == ["{not json}", "b"]


def test_salvages_a_payload_with_escaped_quotes():
    payload = '{"name": "say \\\\"hi\\\\"", "tags": []}'
    recovered = salvage_failed_generation(Person, groq_error(payload))
    assert recovered is not None


def test_returns_none_when_there_is_nothing_to_salvage():
    assert salvage_failed_generation(Person, Exception("connection reset")) is None


def test_returns_none_when_the_payload_does_not_fit_the_schema():
    """A wrong-shaped payload must not be smuggled through as a success."""
    assert salvage_failed_generation(Person, groq_error('{"unrelated": 1}')) is None


def test_returns_none_for_malformed_json():
    assert salvage_failed_generation(Person, groq_error('{"name": ')) is None
