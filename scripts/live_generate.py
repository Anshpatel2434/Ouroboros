#!/usr/bin/env python3
"""Run only the generation half against a live model.

    python scripts/live_generate.py [--out DIR] [--spec FILE]

The interview is already proven to converge; this exercises what is not — backlog
planning, skeleton planning, rendering and self-review — from a spec that has
already passed the ambiguity lint. It costs roughly a fifth of a full run, which
matters against a daily token ceiling.

Without --spec it uses the noteseek spec a real interview produced, so the input
is something the product actually generated rather than something invented to
make generation look good.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from ouroboros.generator.build import GeneratorDeps, emit, generate  # noqa: E402
from ouroboros.inquisitor.lint import lint_spec  # noqa: E402
from ouroboros.llm.client import build_llm, describe_configuration  # noqa: E402
from ouroboros.models.spec import (  # noqa: E402
    Component,
    ProjectSpec,
    Requirement,
    StackProfile,
    VerificationPlan,
)

# Reconstructed from the interview that reached "PASS — spec is unambiguous".
NOTESEEK = ProjectSpec(
    name="NoteSeek",
    slug="noteseek",
    one_line="Search your markdown notes from the terminal.",
    problem=(
        "Finding specific information across a growing collection of markdown "
        "notes is slow without an index, and grep gives no relevance ordering."
    ),
    success_criteria=[
        "Indexing 5000 markdown files completes in under 60 seconds.",
        "A search returns its results in under 300 milliseconds.",
        "The CLI prints usage and exits 0 when run with --help.",
    ],
    non_goals=[
        "No web or graphical interface.",
        "No cloud sync or remote storage.",
        "No note editing.",
        "No formats other than markdown.",
    ],
    stack=StackProfile(
        language="Python",
        language_version="3.12",
        framework=None,
        package_manager="uv",
        database="SQLite",
        key_libraries=["watchdog", "rich", "pytest", "ruff"],
        corpus_covered=True,
    ),
    verification=VerificationPlan(
        install="uv sync",
        test="uv run pytest -q",
        lint="uv run ruff check .",
        smoke="uv run noteseek --help",
    ),
    components=[
        Component(
            name="indexer",
            responsibility="Builds and updates the SQLite FTS5 index from markdown files.",
            paths=["src/noteseek/indexer.py"],
        ),
        Component(
            name="searcher",
            responsibility="Runs ranked queries against the index and returns hits.",
            paths=["src/noteseek/searcher.py"],
        ),
        Component(
            name="watcher",
            responsibility="Watches a directory and re-indexes files as they change.",
            paths=["src/noteseek/watcher.py"],
        ),
        Component(
            name="cli",
            responsibility="Parses the index, search and watch commands and dispatches them.",
            paths=["src/noteseek/cli.py"],
        ),
    ],
    requirements=[
        Requirement(
            id="R-001",
            statement="Index every markdown file under a directory into SQLite FTS5.",
            acceptance_criteria=[
                "Running `noteseek index ./notes` creates notes.db containing an FTS5 table.",
                "Every .md file under ./notes has one row in that table.",
            ],
        ),
        Requirement(
            id="R-002",
            statement="Skip hidden directories and node_modules while indexing.",
            acceptance_criteria=[
                "A file under ./notes/.git/ produces no row in the index.",
                "A file under ./notes/node_modules/ produces no row in the index.",
            ],
            depends_on=["R-001"],
        ),
        Requirement(
            id="R-003",
            statement="Remove index entries for files that no longer exist.",
            acceptance_criteria=[
                "After deleting a file and re-running index, that file has no rows in the index.",
            ],
            depends_on=["R-001"],
        ),
        Requirement(
            id="R-004",
            statement="Search the index and print matching files with line numbers.",
            acceptance_criteria=[
                'Running `noteseek search "term"` exits 0.',
                'Each output line is formatted as "<file_path>:<line_number>: <snippet>".',
            ],
            depends_on=["R-001"],
        ),
        Requirement(
            id="R-005",
            statement="Return at most 20 search hits ordered by bm25 relevance.",
            acceptance_criteria=[
                "A query matching 50 files prints exactly 20 result lines.",
                "Results are ordered by descending bm25 score.",
                "Ties in score are ordered by ascending file path.",
            ],
            depends_on=["R-004"],
        ),
        Requirement(
            id="R-006",
            statement="Re-index changed files while watching a directory.",
            acceptance_criteria=[
                "Running `noteseek watch ./notes` prints 'watching ./notes' and stays running.",
                "Creating a .md file under ./notes adds its rows to the index within 2 seconds.",
            ],
            depends_on=["R-001"],
        ),
        Requirement(
            id="R-007",
            statement="Expose index, search and watch as CLI subcommands.",
            acceptance_criteria=[
                "`noteseek --help` exits 0 and lists index, search and watch.",
                "`noteseek search` with no query exits non-zero and prints an error.",
            ],
        ),
    ],
    glossary={
        "index": "The SQLite FTS5 database built from the markdown files.",
        "hit": "One matching line returned by a search.",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    parser.add_argument("--spec", default=None, help="A spec JSON file to use instead.")
    args = parser.parse_args()

    config = describe_configuration()
    print(f"provider={config['provider']} model={config['model']} critic={config['critic_model']}")

    spec = (
        ProjectSpec.model_validate_json(Path(args.spec).read_text(encoding="utf-8"))
        if args.spec
        else NOTESEEK
    )

    report = lint_spec(spec)
    print(f"lint: {report.summary()}")
    if not report.passed:
        for finding in report.errors:
            print(f"  [{finding.code}] {finding.location}: {finding.evidence}")
        return 2

    print(f"\nspec: {spec.name} — {len(spec.requirements)} requirements, "
          f"{len(spec.components)} components")

    started = time.time()
    print("\n=== GENERATION ===")
    result = generate(
        spec, GeneratorDeps(llm=build_llm("default"), critic=build_llm("critic"))
    )
    print(f"review: {result.review.summary()} (attempts={result.attempts}) "
          f"in {time.time() - started:.0f}s")
    for finding in result.review.findings:
        flag = "BLOCK" if finding.blocking else "note "
        print(f"  {flag} [{finding.location}] {finding.issue}")
    for note in result.blueprint.notes:
        print(f"  note: {note}")

    backlog = result.blueprint.backlog
    covered = {t.requirement_id for t in backlog.tasks if t.requirement_id}
    missing = [r.id for r in spec.requirements if r.id not in covered]

    print(f"\nbacklog: {len(backlog.tasks)} tasks, "
          f"{len(covered)}/{len(spec.requirements)} requirements covered")
    if missing:
        print(f"  UNCOVERED: {', '.join(missing)}")
    for task in backlog.tasks:
        print(f"  {task.id} [{task.requirement_id or '--'}] {task.title}")
        print(f"       scope={','.join(task.scope_paths)}")

    destination = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="noteseek-"))
    emit(result.blueprint, destination)
    print(f"\n{len(result.blueprint.files)} files -> {destination}")

    skeleton = [
        f.path
        for f in result.blueprint.files
        if not f.path.startswith(
            ("CLAUDE.md", "spec.md", "README.md", "verify.sh", "init.sh",
             "task_backlog.json", ".git", "state/", "runner/", "checks/")
        )
    ]
    print(f"skeleton files: {', '.join(skeleton) or 'NONE'}")

    bash = shutil.which("bash")
    if bash:
        print("\n=== SHELL SYNTAX OF WHAT WE GENERATED ===")
        for name in ["verify.sh", "init.sh", ".githooks/pre-commit"] + [
            f"checks/{t.id}.sh" for t in backlog.tasks
        ]:
            path = destination / name
            if not path.exists():
                print(f"  MISSING {name}")
                continue
            proc = subprocess.run(
                [bash, "-n", str(path)], capture_output=True, text=True
            )
            status = "ok" if proc.returncode == 0 else "SYNTAX ERROR"
            print(f"  {status:12} {name}"
                  + (f"  {proc.stderr.strip()[:120]}" if proc.returncode else ""))

    print(f"\ntotal {time.time() - started:.0f}s")
    return 0 if result.accepted else 3


if __name__ == "__main__":
    sys.exit(main())
