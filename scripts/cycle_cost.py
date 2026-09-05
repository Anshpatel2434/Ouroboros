#!/usr/bin/env python3
"""Measure what one complete interview-and-generate cycle actually costs.

    python scripts/cycle_cost.py

Runs the whole product on a real project brief, with a second model standing in
for the developer, and reports the tokens the provider actually billed rather
than an estimate from prompt lengths.

The simulated developer is reported separately: a real user answers the
questions themselves, so that spend is an artefact of automated testing and not
part of what a cycle costs in production.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from ouroboros.generator.build import GeneratorDeps, generate  # noqa: E402
from ouroboros.inquisitor.graph import InquisitorDeps, InterviewSession  # noqa: E402
from ouroboros.llm.client import build_llm, describe_configuration  # noqa: E402
from ouroboros.llm.usage import LEDGER, PRICING, reset_usage  # noqa: E402
from ouroboros.models.spec import ProjectSpec  # noqa: E402
from scripts.live_smoke import BRIEF, answer_questions  # noqa: E402

SIMULATION_ROLE = "simulated_developer"


class RoleTaggedLLM:
    """Wraps an LLM so its calls are attributed to a fixed role in the ledger."""

    def __init__(self, inner, role: str):
        self._inner = inner
        self._role = role

    def structured(self, schema, system, user, role="default"):
        return self._inner.structured(schema, system, user, role=self._role)


def main() -> int:
    config = describe_configuration()
    print(f"provider={config['provider']} model={config['model']}")
    price = PRICING.get(str(config["model"]))
    if price:
        print(f"price: ${price.input_per_million}/1M in, "
              f"${price.output_per_million}/1M out (checked {price.checked})")
    else:
        print(f"price: no verified price recorded for {config['model']}")

    reset_usage()
    started = time.time()

    session = InterviewSession(
        "cost-run", deps=InquisitorDeps(llm=build_llm("default"), max_rounds=8)
    )
    developer = RoleTaggedLLM(build_llm("fast"), SIMULATION_ROLE)

    print("\n=== INTERVIEW ===")
    state = session.start(BRIEF)
    rounds = 0
    while state["status"] == "interviewing" and state["questions"]:
        rounds += 1
        replies = answer_questions(developer, state["questions"])
        state = session.answer(replies)
        print(f"  round {rounds}: {len(replies)} answered, "
              f"{LEDGER.total_tokens:,} tokens so far")

    interview_seconds = time.time() - started
    print(f"interview: status={state['status']} rounds={rounds} "
          f"in {interview_seconds:.0f}s")

    if state["status"] != "ready":
        print("\nInterview did not converge; cost below covers the interview only.")
        print(LEDGER.table())
        return 2

    print("\n=== GENERATION ===")
    generation_started = time.time()
    result = generate(
        ProjectSpec.model_validate(state["spec"]),
        GeneratorDeps(llm=build_llm("default"), critic=build_llm("critic")),
    )
    generation_seconds = time.time() - generation_started
    print(f"review: {result.review.summary()} (attempts={result.attempts}) "
          f"in {generation_seconds:.0f}s")
    print(f"backlog: {len(result.blueprint.backlog.tasks)} tasks, "
          f"{len(result.blueprint.files)} files")

    print("\n=== BILLED TOKENS, BY ROLE ===")
    print(LEDGER.table())

    product = LEDGER.excluding(SIMULATION_ROLE)
    simulation = LEDGER.by_role().get(SIMULATION_ROLE)

    print("\n=== WHAT A REAL CYCLE COSTS ===")
    print(f"wall clock:        {time.time() - started:.0f}s "
          f"(interview {interview_seconds:.0f}s + generation {generation_seconds:.0f}s)")
    print(f"model calls:       {len(product.calls)}")
    print(f"input tokens:      {product.input_tokens:,}")
    print(f"output tokens:     {product.output_tokens:,}")
    print(f"total tokens:      {product.total_tokens:,}")

    cost = product.cost
    if cost is None:
        print(f"cost:              unpriced models: {', '.join(product.unpriced_models)}")
    else:
        print(f"COST PER CYCLE:    ${cost:.4f}")
        print(f"  100 cycles:      ${cost * 100:.2f}")
        print(f"  1000 cycles:     ${cost * 1000:.2f}")

    if simulation:
        sim_cost = simulation.cost
        money = f"${sim_cost:.4f}" if sim_cost is not None else "unpriced"
        print(f"\nexcluded: simulated developer, {simulation.total_tokens:,} tokens "
              f"({money}). A real user answers these themselves.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
