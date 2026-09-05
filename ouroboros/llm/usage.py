"""Token accounting.

Every model call is recorded with the role that made it, so the cost of a run
can be attributed to the interview, the lint, generation, or the critic rather
than arriving as one opaque number. Estimating token spend from prompt lengths
is guesswork; this reads what the provider actually billed.

Prices are per million tokens and were taken from the provider's own pricing
page rather than remembered. They go stale — `PRICING` names the date each was
checked, and an unknown model is reported as unpriced instead of guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input_per_million: float
    output_per_million: float
    checked: str

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_million
            + output_tokens * self.output_per_million
        ) / 1_000_000


PRICING: dict[str, ModelPrice] = {
    # developers.openai.com/api/docs/pricing
    "gpt-4o-mini": ModelPrice(0.15, 0.60, "2026-09-05"),
}


def price_for(model: str) -> ModelPrice | None:
    """Look up a price, tolerating the dated ids providers actually report.

    A call billed against `gpt-4o-mini` comes back from the API as
    `gpt-4o-mini-2024-07-18`. Exact-match lookup silently reported every run as
    unpriced, which is worse than wrong — it looks like missing data rather than
    a naming mismatch. Longest matching prefix wins so a future
    `gpt-4o-mini-high` entry would beat the generic one.
    """
    if model in PRICING:
        return PRICING[model]
    candidates = [name for name in PRICING if model.startswith(name)]
    return PRICING[max(candidates, key=len)] if candidates else None


@dataclass
class Call:
    role: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost(self) -> float | None:
        price = price_for(self.model)
        return price.cost(self.input_tokens, self.output_tokens) if price else None


@dataclass
class UsageLedger:
    """Accumulates calls for one run."""

    calls: list[Call] = field(default_factory=list)

    def record(self, role: str, model: str, input_tokens: int, output_tokens: int) -> None:
        self.calls.append(Call(role, model, input_tokens, output_tokens))

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost(self) -> float | None:
        """None when any call used a model we have no verified price for."""
        costs = [c.cost for c in self.calls]
        if not costs or any(c is None for c in costs):
            return None
        return sum(costs)  # type: ignore[arg-type]

    @property
    def unpriced_models(self) -> set[str]:
        return {c.model for c in self.calls if price_for(c.model) is None}

    def by_role(self) -> dict[str, "UsageLedger"]:
        grouped: dict[str, UsageLedger] = {}
        for call in self.calls:
            grouped.setdefault(call.role, UsageLedger()).calls.append(call)
        return grouped

    def excluding(self, *roles: str) -> "UsageLedger":
        """A ledger without certain roles — used to separate simulation from product."""
        return UsageLedger(calls=[c for c in self.calls if c.role not in roles])

    def table(self) -> str:
        lines = [f"{'role':<12} {'calls':>5} {'in':>9} {'out':>8} {'cost':>10}"]
        for role, ledger in sorted(
            self.by_role().items(), key=lambda item: -item[1].total_tokens
        ):
            cost = ledger.cost
            money = f"${cost:.6f}" if cost is not None else "unpriced"
            lines.append(
                f"{role:<12} {len(ledger.calls):>5} {ledger.input_tokens:>9,} "
                f"{ledger.output_tokens:>8,} {money:>10}"
            )
        total = self.cost
        money = f"${total:.6f}" if total is not None else "unpriced"
        lines.append(
            f"{'TOTAL':<12} {len(self.calls):>5} {self.input_tokens:>9,} "
            f"{self.output_tokens:>8,} {money:>10}"
        )
        return "\n".join(lines)


# One ledger per process. The product is a local single-user tool, so a module
# level ledger is the honest shape; a server handling many users would scope it
# per session instead.
LEDGER = UsageLedger()


def reset_usage() -> None:
    LEDGER.calls.clear()
