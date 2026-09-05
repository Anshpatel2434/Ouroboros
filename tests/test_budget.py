"""Token budgeting and pacing.

These exist because a real 413 taught us the rule: Groq's free tier allows 8,000
tokens per minute and counts requested output against it, so a request must fit
prompt plus max_tokens inside that budget.
"""

from __future__ import annotations


from ouroboros.llm.budget import (
    ANTHROPIC_LIMITS,
    GROQ_LIMITS,
    TokenRateLimiter,
    estimate_tokens,
    trim_to_tokens,
)


def test_estimate_is_pessimistic():
    """Underestimating costs a 413; overestimating costs a slightly shorter prompt."""
    text = "def add(a, b):\n    return a + b\n" * 20
    assert estimate_tokens(text) >= len(text) / 4


def test_trim_keeps_head_and_tail():
    text = "HEAD" + ("x" * 20_000) + "TAIL"
    trimmed, was_trimmed = trim_to_tokens(text, 200)

    assert was_trimmed
    assert trimmed.startswith("HEAD")
    assert trimmed.endswith("TAIL")
    assert estimate_tokens(trimmed) <= 220


def test_trim_leaves_short_text_alone():
    trimmed, was_trimmed = trim_to_tokens("short enough", 500)
    assert trimmed == "short enough"
    assert not was_trimmed


def test_groq_request_fits_inside_the_minute():
    """The exact failure that broke the first live run must not be expressible."""
    for role in ("questions", "draft", "backlog", "skeleton", "review", "lint", "research"):
        total = GROQ_LIMITS.prompt_budget(role) + GROQ_LIMITS.output_for(role)
        assert total <= GROQ_LIMITS.tokens_per_minute, f"{role} would 413"


def test_skeleton_gets_the_largest_output_allowance():
    """Skeleton plans carry whole file contents; question batches never do."""
    assert GROQ_LIMITS.output_for("skeleton") > GROQ_LIMITS.output_for("questions")


def test_anthropic_is_not_rate_constrained():
    assert ANTHROPIC_LIMITS.tokens_per_minute is None
    assert ANTHROPIC_LIMITS.prompt_budget("review") > GROQ_LIMITS.prompt_budget("review")


class FakeClock:
    """A clock that only moves when the limiter sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_limiter_admits_requests_inside_the_window():
    clock = FakeClock()
    limiter = TokenRateLimiter(1000, clock=clock, sleeper=clock.sleep)

    limiter.acquire(400)
    limiter.acquire(400)

    assert clock.slept == [], "requests inside the budget must not wait"
    assert limiter.spent_in_window() == 800


def test_limiter_blocks_until_the_window_rolls():
    clock = FakeClock()
    limiter = TokenRateLimiter(1000, clock=clock, sleeper=clock.sleep)

    limiter.acquire(900)
    limiter.acquire(900)

    assert clock.slept, "a second oversized request must wait for the window to roll"
    assert sum(clock.slept) >= TokenRateLimiter.WINDOW_SECONDS
    # The first request has aged out, so only the second is still counted.
    assert limiter.spent_in_window() == 900


def test_limiter_paces_a_realistic_groq_run():
    """Six 3,000-token calls against an 8,000 TPM budget must spread over minutes."""
    clock = FakeClock()
    limiter = TokenRateLimiter(8000, clock=clock, sleeper=clock.sleep)

    for _ in range(6):
        limiter.acquire(3000)

    assert clock.now - 1000.0 >= 120, "pacing must span more than one window"
    assert limiter.spent_in_window() <= 8000


def test_unlimited_limiter_never_blocks():
    clock = FakeClock()
    TokenRateLimiter(None, clock=clock, sleeper=clock.sleep).acquire(1_000_000)
    assert clock.slept == []


def test_oversized_single_request_is_still_admitted():
    """A lone request bigger than the whole window must not deadlock the run."""
    clock = FakeClock()
    limiter = TokenRateLimiter(1000, clock=clock, sleeper=clock.sleep)

    limiter.acquire(5000)

    assert clock.slept == []
    assert limiter.spent_in_window() == 5000


def test_draft_role_can_carry_a_whole_spec():
    """A live run truncated a draft mid-JSON at 2,200 tokens.

    The draft is the entire spec returned in full every round, so it needs
    nearly the whole output budget. A trimmed prompt still works; a truncated
    response does not parse at all.
    """
    assert GROQ_LIMITS.output_for("draft") >= 4500
    assert GROQ_LIMITS.output_for("draft") > GROQ_LIMITS.output_for("questions") * 3
    # And it must still fit inside the minute.
    assert (
        GROQ_LIMITS.output_for("draft") + GROQ_LIMITS.prompt_budget("draft")
        <= GROQ_LIMITS.tokens_per_minute
    )


def test_every_role_still_leaves_room_for_a_real_prompt():
    for role in ("questions", "draft", "backlog", "skeleton", "review"):
        assert GROQ_LIMITS.prompt_budget(role) >= 512, role
