"""Provider selection. No network: these only exercise configuration."""

from __future__ import annotations

import pytest

from ouroboros.llm.client import (
    PROVIDER_MODELS,
    AnthropicLLM,
    GroqLLM,
    OpenAILLM,
    active_provider,
    build_llm,
    describe_configuration,
    model_for,
)

ENV_VARS = [
    "OUROBOROS_LLM_PROVIDER",
    "OUROBOROS_DEFAULT_MODEL",
    "OUROBOROS_CRITIC_MODEL",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """A .env is loaded at import time; each test starts from a known state."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_groq_is_chosen_when_its_key_is_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert active_provider() == "groq"


def test_openai_is_chosen_when_its_key_is_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert active_provider() == "openai"


def test_anthropic_is_chosen_when_only_its_key_is_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert active_provider() == "anthropic"


def test_provider_precedence_is_openai_then_groq_then_anthropic(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert active_provider() == "groq"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert active_provider() == "openai"


def test_explicit_provider_overrides_the_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OUROBOROS_LLM_PROVIDER", "anthropic")
    assert active_provider() == "anthropic"


def test_unknown_provider_fails_loudly(monkeypatch):
    monkeypatch.setenv("OUROBOROS_LLM_PROVIDER", "mistral")
    with pytest.raises(RuntimeError, match="expected one of"):
        active_provider()


def test_model_defaults_per_provider():
    assert model_for("default", "groq") == "openai/gpt-oss-120b"
    assert model_for("default", "openai") == "gpt-4o-mini"
    assert model_for("default", "anthropic") == "claude-sonnet-5"


def test_model_override_is_respected(monkeypatch):
    monkeypatch.setenv("OUROBOROS_DEFAULT_MODEL", "openai/gpt-oss-20b")
    assert model_for("default", "groq") == "openai/gpt-oss-20b"


def test_every_provider_defines_every_role():
    for provider, roles in PROVIDER_MODELS.items():
        assert {"default", "critic", "fast"} <= set(roles), provider


def test_build_llm_returns_the_matching_implementation(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert isinstance(build_llm("default"), GroqLLM)

    monkeypatch.setenv("OUROBOROS_LLM_PROVIDER", "openai")
    assert isinstance(build_llm("default"), OpenAILLM)

    monkeypatch.setenv("OUROBOROS_LLM_PROVIDER", "anthropic")
    assert isinstance(build_llm("critic"), AnthropicLLM)


def test_missing_key_is_reported_before_any_request(monkeypatch):
    """Construction is lazy, so the error must arrive on first use, not silently."""
    monkeypatch.setenv("OUROBOROS_LLM_PROVIDER", "groq")
    llm = build_llm("default")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        llm._client(1024)


def test_health_configuration_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value")
    described = describe_configuration()

    assert described["provider"] == "groq"
    assert described["api_key_present"] is True
    assert "gsk_secret_value" not in str(described)


def test_daily_and_minute_limits_are_told_apart():
    """Waiting fixes a per-minute limit and does nothing for a per-day one."""
    from ouroboros.llm.client import _is_daily_limit, _is_rate_limit

    per_minute = (
        "Error code: 413 - Request too large for model in organization on tokens "
        "per minute (TPM): Limit 8000, Requested 9317"
    )
    per_day = (
        "Error code: 429 - Rate limit reached for model in organization on tokens "
        "per day (TPD): Limit 200000, Used 197402, Requested 3049"
    )

    assert _is_rate_limit(Exception(per_minute))
    assert not _is_daily_limit(Exception(per_minute))

    assert _is_daily_limit(Exception(per_day))
    assert not _is_daily_limit(Exception("connection reset"))
