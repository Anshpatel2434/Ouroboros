"""Token budgeting and rate pacing.

Written against a real constraint rather than a guessed one: Groq's free tier
allows 8,000 tokens per minute, and it counts the requested `max_tokens` toward
that budget. A request asking for an 8,192-token completion is therefore over
the limit before a single character of prompt is added, and comes back 413.

So three things live here: an estimate of how many tokens a string costs, a
trimmer that keeps prompts inside their share of the budget, and a limiter that
paces requests across the rolling minute.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

# Deliberately pessimistic. Code and JSON tokenize worse than prose, and
# underestimating here means a 413 instead of a slightly shorter prompt.
CHARS_PER_TOKEN = 3.2

TRUNCATION_MARKER = "\n\n[... trimmed to fit the model's token budget ...]\n\n"


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def tokens_to_chars(tokens: int) -> int:
    return int(tokens * CHARS_PER_TOKEN)


def trim_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    """Trim from the middle, keeping the head and tail. Returns (text, trimmed).

    The middle goes because instructions cluster at the start and the most
    recent, most specific context clusters at the end; the least load-bearing
    material is in between.
    """
    if estimate_tokens(text) <= max_tokens:
        return text, False

    budget = tokens_to_chars(max_tokens) - len(TRUNCATION_MARKER)
    if budget <= 0:
        return TRUNCATION_MARKER, True

    head = int(budget * 0.65)
    tail = budget - head
    return text[:head] + TRUNCATION_MARKER + text[-tail:], True


@dataclass(frozen=True)
class ProviderLimits:
    """What one provider will actually accept, per minute and per request."""

    tokens_per_minute: int | None
    max_prompt_tokens: int
    max_output_tokens: int

    def output_for(self, role: str) -> int:
        """Per-role output caps.

        Some steps legitimately need long outputs — a skeleton plan carries whole
        file contents — while a question batch never does. Sizing them separately
        is what makes a tight per-minute budget usable at all.
        """
        share = {
            "questions": 0.30,
            "draft": 0.55,
            "backlog": 0.75,
            "skeleton": 1.00,
            "review": 0.45,
            "lint": 0.35,
            "research": 0.55,
            "default": 0.55,
        }.get(role, 0.55)
        return max(512, int(self.max_output_tokens * share))

    def prompt_budget(self, role: str = "default") -> int:
        """Prompt tokens left once this role's output is reserved."""
        if self.tokens_per_minute is None:
            return self.max_prompt_tokens
        room = self.tokens_per_minute - self.output_for(role)
        # A safety margin: the provider's tokenizer is not ours.
        return max(512, min(self.max_prompt_tokens, int(room * 0.85)))


# Free-tier Groq: 8,000 TPM, and max_tokens counts against it.
GROQ_LIMITS = ProviderLimits(
    tokens_per_minute=8000, max_prompt_tokens=5000, max_output_tokens=4000
)

# Anthropic's limits are far higher; nothing here is the binding constraint.
ANTHROPIC_LIMITS = ProviderLimits(
    tokens_per_minute=None, max_prompt_tokens=120_000, max_output_tokens=8192
)


class TokenRateLimiter:
    """A rolling-minute token bucket, shared across threads.

    Requests are admitted only when the last sixty seconds of spend leaves room
    for this one. Without it a multi-step run trips the limit halfway through
    and loses the work already paid for.

    The clock and sleep are injected: a limiter whose only honest test takes a
    real minute does not get tested.
    """

    WINDOW_SECONDS = 60.0

    def __init__(
        self,
        tokens_per_minute: int | None,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self.tokens_per_minute = tokens_per_minute
        self._clock = clock
        self._sleep = sleeper
        self._spent: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        while self._spent and now - self._spent[0][0] > self.WINDOW_SECONDS:
            self._spent.popleft()

    def spent_in_window(self) -> int:
        with self._lock:
            self._prune(self._clock())
            return sum(tokens for _, tokens in self._spent)

    def acquire(self, tokens: int, on_wait=None) -> None:
        """Block until `tokens` fit in the current window, then record them."""
        if self.tokens_per_minute is None:
            return

        while True:
            with self._lock:
                now = self._clock()
                self._prune(now)
                used = sum(amount for _, amount in self._spent)

                # An empty window admits anything: a single request larger than
                # the whole quota must fail at the provider, not deadlock here.
                if used + tokens <= self.tokens_per_minute or not self._spent:
                    self._spent.append((now, tokens))
                    return

                oldest = self._spent[0][0]
                wait = max(0.5, self.WINDOW_SECONDS - (now - oldest) + 0.5)

            if on_wait:
                on_wait(wait, used, tokens)
            self._sleep(wait)
