#!/usr/bin/env python3
"""Take one project through the whole product against a live model.

    python scripts/live_smoke.py [--out DIR] [--rounds N]

A second model plays the developer, answering the Inquisitor's questions from a
fixed project description. That is not a substitute for a human interview, but
it exercises every real component — questioning, integration, gap research,
both lint stages, backlog and skeleton planning, rendering, and self-review —
against a real model instead of a fake.

It costs tokens and needs a network. It is deliberately not part of the test
suite, which must stay runnable with no key.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Models emit typographic characters (non-breaking hyphens, dashes) that the
# Windows console's cp1252 codec cannot encode. Printing must never be what
# fails a run that has already spent real tokens.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        # line_buffering so a redirected long run streams instead of appearing
        # only at exit.
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from pydantic import BaseModel, Field  # noqa: E402

from ouroboros.generator.build import GeneratorDeps, emit, generate  # noqa: E402
from ouroboros.inquisitor.graph import InquisitorDeps, InterviewSession  # noqa: E402
from ouroboros.llm.client import build_llm, describe_configuration  # noqa: E402
from ouroboros.models.spec import ProjectSpec  # noqa: E402

BRIEF = (
    "A command-line tool that watches a folder of markdown notes and keeps a "
    "searchable index, so I can find anything in my notes from the terminal."
)

# What the simulated developer knows and will answer from. A real interview
# would extract this; here it stands in for the human's intent.
PROJECT_FACTS = """\
You are the developer who wants this built. Answer the interviewer's questions
concretely and decisively from these facts. Never say "I'm not sure" or "up to
you" — invent a specific, sensible answer if the facts do not cover it.

- The tool is called `noteseek`. Single-user, runs locally, no server.
- Python 3.12, packaged with uv. Tests with pytest. Lint with ruff.
- Index stored in a local SQLite file using FTS5. No external services.
- Commands: `noteseek index <dir>` builds/updates the index,
  `noteseek search <query>` prints matching files with line numbers,
  `noteseek watch <dir>` re-indexes on file changes.
- Search must return results ranked by relevance, showing at most 20 hits.
- Only .md files are indexed. Hidden folders and node_modules are skipped.
- Success: I can index 5000 notes and get search results in under 300 ms.
- Not in scope: no web UI, no cloud sync, no editing notes, no PDF support.
- Deleted files must disappear from the index on the next run.
"""


class SimulatedAnswer(BaseModel):
    question_id: str
    value: str = Field(description="A concrete, decisive answer.")


class SimulatedAnswers(BaseModel):
    answers: list[SimulatedAnswer] = Field(default_factory=list)


def answer_questions(developer, questions: list[dict]) -> list[dict[str, str]]:
    rendered = "\n\n".join(
        f"[{q['id']}] ({q['header']}) {q['text']}\n"
        f"Why they ask: {q['why_it_matters']}\n"
        + (
            "Options: " + ", ".join(o["label"] for o in q["options"])
            if q.get("options")
            else "Free text."
        )
        for q in questions
    )
    result = developer.structured(
        SimulatedAnswers,
        system=PROJECT_FACTS,
        user=f"Answer each question. Use the exact question ids.\n\n{rendered}",
    )
    return [{"question_id": a.question_id, "value": a.value} for a in result.answers]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="Where to write the generated repo.")
    parser.add_argument("--rounds", type=int, default=8, help="Interview round cap.")
    args = parser.parse_args()

    config = describe_configuration()
    print(f"provider={config['provider']} model={config['model']} "
          f"critic={config['critic_model']} key={'yes' if config['api_key_present'] else 'NO'}")
    if not config["api_key_present"]:
        print("No API key. Put one in .env first.")
        return 1

    interviewer = build_llm("default")
    developer = build_llm("fast")
    started = time.time()

    session = InterviewSession(
        "live-smoke",
        deps=InquisitorDeps(llm=interviewer, max_rounds=args.rounds),
    )

    print("\n=== INTERVIEW ===")
    state = session.start(BRIEF)

    while state["status"] == "interviewing" and state["questions"]:
        print(f"\n-- round {state['round']} --")
        for question in state["questions"]:
            print(f"  Q ({question['header']}): {question['text']}")

        replies = answer_questions(developer, state["questions"])
        for reply in replies:
            print(f"  A: {reply['value'][:150]}")

        state = session.answer(replies)
        if state["lint_summary"]:
            print(f"  lint: {state['lint_summary']}")
        for notice in state["notices"]:
            print(f"  note: {notice}")

    print(f"\ninterview finished: status={state['status']} "
          f"rounds={state['round']} elapsed={time.time() - started:.0f}s")

    if state["status"] != "ready":
        print("\nGeneration refused, which is the correct behaviour for an unclean spec.")
        print(f"missing fields: {', '.join(state['missing_fields']) or 'none'}")
        for notice in state["notices"]:
            print(f"  note: {notice}")
        for finding in (state["lint"] or {}).get("findings", []):
            print(f"  [{finding['severity']}] {finding['code']} {finding['location']}: "
                  f"{finding['evidence'][:120]}")
        print("\ndraft captured so far:")
        draft = state["draft"]
        for key in ("name", "one_line", "problem"):
            print(f"  {key}: {str(draft.get(key))[:100]}")
        print(f"  requirements: {len(draft.get('requirements') or [])}")
        print(f"  components: {len(draft.get('components') or [])}")
        print(f"  stack: {draft.get('stack')}")
        print(f"  verification: {draft.get('verification')}")
        return 2

    spec = ProjectSpec.model_validate(state["spec"])
    print(f"\nspec: {spec.name} — {len(spec.requirements)} requirements, "
          f"{len(spec.components)} components")
    print(f"stack: {spec.stack.language} {spec.stack.language_version} / "
          f"{spec.stack.framework or 'no framework'} / {spec.stack.package_manager}")
    print(f"verify: {', '.join(c for _, c in spec.verification.commands())}")

    print("\n=== GENERATION ===")
    result = generate(spec, GeneratorDeps(llm=build_llm("default"), critic=build_llm("critic")))
    print(f"review: {result.review.summary()} (attempts={result.attempts})")
    for finding in result.review.findings:
        flag = "BLOCK" if finding.blocking else "note "
        print(f"  {flag} [{finding.location}] {finding.issue}")

    destination = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="noteseek-"))
    emit(result.blueprint, destination)
    print(f"\n{len(result.blueprint.files)} files -> {destination}")
    print(f"backlog: {len(result.blueprint.backlog.tasks)} tasks")
    for task in result.blueprint.backlog.tasks:
        print(f"  {task.id} {task.title}  scope={','.join(task.scope_paths)}")

    # The check the product's own gate does not perform. Reporting it here is
    # the evidence for whether that gate needs strengthening.
    bash = shutil.which("bash")
    if bash:
        print("\n=== DOES THE GENERATED REPO ACTUALLY VERIFY? ===")
        proc = subprocess.run(
            [bash, "verify.sh"], cwd=destination, capture_output=True, text=True, timeout=300
        )
        print(f"verify.sh exit={proc.returncode}")
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
        for line in tail:
            print("  " + line)

    print(f"\ntotal elapsed {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
