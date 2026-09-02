"""Renderers for every file in a generated harness repo.

Templates use %%TOKEN%% placeholders rather than f-strings or str.format,
because almost everything here is shell or JSON: `${VAR}` and `{"key": ...}`
collide with both. Explicit replacement is uglier to read and impossible to get
subtly wrong.
"""

from __future__ import annotations

import json

from ouroboros.models.blueprint import Backlog, Task
from ouroboros.models.spec import ProjectSpec, Topology

DYNAMIC_START = "<!-- OUROBOROS:DYNAMIC-DIRECTIVES:START -->"
DYNAMIC_END = "<!-- OUROBOROS:DYNAMIC-DIRECTIVES:END -->"


def _fill(template: str, values: dict[str, str]) -> str:
    for token, value in values.items():
        template = template.replace(f"%%{token}%%", value)
    return template


def _bullets(items: list[str], empty: str = "_None recorded._") -> str:
    return "\n".join(f"- {i}" for i in items) if items else empty


# --------------------------------------------------------------------------- #
# CLAUDE.md — the agent's constitution
# --------------------------------------------------------------------------- #

CLAUDE_MD = """# %%NAME%% — Agent Constitution

%%ONE_LINE%%

You are building this project autonomously. This file is your standing order.
It outranks your own judgement about what would be nicer to do.

## The loop

1. Read `state/progress.json` to find the active task.
2. Read that task in `task_backlog.json`. Read `spec.md` if you need the wider goal.
3. Implement the task. **Touch only the paths in the task's `scope_paths`.**
4. Run `./verify.sh`. It must exit 0.
5. Run `./checks/<task-id>.sh`. It must exit 0.
6. Commit, with the task id in the message. One task, one commit.
7. Update `state/progress.json` and append your reasoning to `state/decisions.log`.

If step 4 or 5 fails, fix your work and retry. After %%MAX_ATTEMPTS%% failed
attempts on one task, stop, write what you learned to `state/decisions.log`, and
leave the task for a human.

## Hard rules

- **Never edit these paths:** %%PROTECTED%%. They are the guardrails you operate
  under. If one of them seems wrong, say so in `state/decisions.log` and stop —
  do not fix it yourself.
- **Never weaken a test to make it pass.** Deleting, skipping, or loosening an
  assertion to get green is a failure, not a success. The same goes for
  hardcoding a value that a test checks for.
- **Never mark a task complete without a green `./verify.sh`.**
- **Never work outside the active task's scope.** If you believe a change is
  needed elsewhere, record it in `state/decisions.log` and continue with the
  task at hand.
- **Never invent requirements.** If the spec does not say it, it is not in scope.
  See the non-goals below.

## What this project is

%%PROBLEM%%

**Success looks like:**
%%SUCCESS%%

**Explicit non-goals — do not build these:**
%%NON_GOALS%%

## Stack

- Language: %%LANGUAGE%% %%LANGUAGE_VERSION%%
- Framework: %%FRAMEWORK%%
- Package manager: %%PACKAGE_MANAGER%%

Verification is `./verify.sh`, which runs:

%%VERIFY_STEPS%%

## Definitions

%%GLOSSARY%%

""" + DYNAMIC_START + """
_No dynamic directives yet. This section is maintained by tooling; do not edit
it by hand — anything you write here may be overwritten._
""" + DYNAMIC_END + """
"""


def render_claude_md(spec: ProjectSpec) -> str:
    steps = "\n".join(f"- `{cmd}`" for _, cmd in spec.verification.commands())
    glossary = (
        "\n".join(f"- **{term}** — {definition}" for term, definition in spec.glossary.items())
        or "_No domain terms defined._"
    )
    return _fill(
        CLAUDE_MD,
        {
            "NAME": spec.name,
            "ONE_LINE": spec.one_line,
            "MAX_ATTEMPTS": str(spec.boundaries.max_attempts_per_task),
            "PROTECTED": ", ".join(f"`{p}`" for p in spec.boundaries.protected_paths),
            "PROBLEM": spec.problem,
            "SUCCESS": _bullets(spec.success_criteria),
            "NON_GOALS": _bullets(spec.non_goals, "_None recorded — ask before expanding scope._"),
            "LANGUAGE": spec.stack.language,
            "LANGUAGE_VERSION": spec.stack.language_version,
            "FRAMEWORK": spec.stack.framework or "none",
            "PACKAGE_MANAGER": spec.stack.package_manager,
            "VERIFY_STEPS": steps,
            "GLOSSARY": glossary,
        },
    )


# --------------------------------------------------------------------------- #
# spec.md — the immutable record
# --------------------------------------------------------------------------- #

def render_spec_md(spec: ProjectSpec) -> str:
    lines = [
        f"# {spec.name} — Specification",
        "",
        f"> {spec.one_line}",
        "",
        "This file is the agreed definition of the project. It is immutable to the",
        "coding agent: every task exists to satisfy something written here.",
        "",
        "## Problem",
        "",
        spec.problem,
        "",
        "## Success criteria",
        "",
        _bullets(spec.success_criteria),
        "",
        "## Non-goals",
        "",
        _bullets(spec.non_goals),
        "",
        "## Stack",
        "",
        f"- Language: {spec.stack.language} {spec.stack.language_version}",
        f"- Framework: {spec.stack.framework or 'none'}",
        f"- Package manager: {spec.stack.package_manager}",
        f"- Database: {spec.stack.database or 'none'}",
    ]
    if spec.stack.key_libraries:
        lines.append(f"- Key libraries: {', '.join(spec.stack.key_libraries)}")

    lines += ["", "## Components", ""]
    for comp in spec.components:
        lines.append(f"### {comp.name}")
        lines.append("")
        lines.append(comp.responsibility)
        lines.append("")
        lines.append(f"Owns: {', '.join(f'`{p}`' for p in comp.paths)}")
        lines.append("")

    lines += ["## Requirements", ""]
    for req in spec.requirements:
        lines.append(f"### {req.id} — {req.statement}")
        lines.append("")
        if req.depends_on:
            lines.append(f"Depends on: {', '.join(req.depends_on)}")
            lines.append("")
        lines.append("Accepted when:")
        lines.append("")
        lines.append(_bullets(req.acceptance_criteria))
        lines.append("")

    if spec.glossary:
        lines += ["## Glossary", ""]
        lines += [f"- **{k}** — {v}" for k, v in spec.glossary.items()]
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Shell entry points
# --------------------------------------------------------------------------- #

VERIFY_SH = """#!/usr/bin/env bash
# The single command that decides whether work is acceptable.
# The agent runs this before every commit; CI runs it on every push.
set -euo pipefail

fail() { echo ""; echo "FAILED: $1"; exit 1; }
step() { echo ""; echo "=== $1 ==="; }

%%STEPS%%

echo ""
echo "verify: all checks passed"
"""


def render_verify_sh(spec: ProjectSpec) -> str:
    blocks = []
    for label, command in spec.verification.commands():
        blocks.append(f'step "{label}"\n{command} || fail "{label}"')
    return _fill(VERIFY_SH, {"STEPS": "\n\n".join(blocks)})


INIT_SH = """#!/usr/bin/env bash
# One-time setup. Run this immediately after cloning, before any agent runs.
set -euo pipefail

echo "=== installing dependencies ==="
%%INSTALL%%

echo "=== wiring git hooks ==="
# Hooks are not cloned with a repository, so they are wired here instead.
git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true
chmod +x verify.sh checks/*.sh 2>/dev/null || true

echo "=== preparing state ==="
mkdir -p state
[ -f state/decisions.log ] || : > state/decisions.log

echo "=== proving the baseline is green ==="
./verify.sh

echo ""
echo "Ready. Start the agent with: python runner/run_agent.py"
"""


def render_init_sh(spec: ProjectSpec) -> str:
    return _fill(INIT_SH, {"INSTALL": spec.verification.install})


PRE_COMMIT = """#!/usr/bin/env bash
# Deterministic gate. Runs before every commit, no model involved.
#
# It enforces two things the agent must never be able to talk its way past:
# the protected paths that hold the guardrails, and the active task's scope
# fence. Full verification is verify.sh; this hook stays fast on purpose.
set -euo pipefail

staged=$(git diff --cached --name-only)
[ -z "$staged" ] && exit 0

protected=(%%PROTECTED%%)
for path in "${protected[@]}"; do
  while IFS= read -r file; do
    [ -z "$file" ] && continue
    case "$file" in
      "$path"|"$path"*)
        echo "BLOCKED: $file is a protected harness path."
        echo "The agent may not modify its own guardrails. Record the concern in"
        echo "state/decisions.log and stop instead."
        exit 1
        ;;
    esac
  done <<< "$staged"
done

# Scope fence: the active task declares the only paths it may touch.
#
# This half needs an interpreter. A repo for a stack without one still gets the
# protected-path enforcement above, which is the guardrail that actually matters;
# losing the fence is a warning, never a blocked commit.
PY_BIN=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys" >/dev/null 2>&1; then
    PY_BIN="$candidate"
    break
  fi
done

if [ -f state/progress.json ] && [ -n "$PY_BIN" ]; then
  out_of_scope=$("$PY_BIN" - "$staged" <<'PY' || true
import json, os, sys

staged = [line.strip() for line in sys.argv[1].splitlines() if line.strip()]
try:
    progress = json.load(open("state/progress.json"))
    backlog = json.load(open("task_backlog.json"))
except Exception:
    sys.exit(0)

active = progress.get("current_task")
task = next((t for t in backlog.get("tasks", []) if t["id"] == active), None)
if not task:
    sys.exit(0)

scope = task.get("scope_paths") or []
if not scope:
    sys.exit(0)

allowed = tuple(scope) + ("state/",)
offenders = [f for f in staged if not f.startswith(allowed)]
print("\\n".join(offenders))
PY
)
  if [ -n "$out_of_scope" ]; then
    echo "BLOCKED: files outside the active task's scope fence:"
    echo "$out_of_scope"
    echo ""
    echo "Widen the task in task_backlog.json only if a human agrees; otherwise"
    echo "restrict the change to the declared scope."
    exit 1
  fi
elif [ -f state/progress.json ]; then
  echo "note: no python interpreter found; scope-fence checking skipped." >&2
fi

exit 0
"""


def render_pre_commit(spec: ProjectSpec) -> str:
    quoted = " ".join(f'"{p}"' for p in spec.boundaries.protected_paths)
    return _fill(PRE_COMMIT, {"PROTECTED": quoted})


WORKFLOW = """name: verify

on:
  push:
  pull_request:

jobs:
  verify:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - name: Run the project's own verification
        run: |
          chmod +x verify.sh checks/*.sh 2>/dev/null || true
          ./verify.sh
"""


def render_workflow() -> str:
    return WORKFLOW


CHECK_SCRIPT = """#!/usr/bin/env bash
# Acceptance check for %%ID%% — %%TITLE%%
#
# Done when:
%%DONE_WHEN%%
set -euo pipefail

%%BODY%%
"""


def render_check_script(task: Task) -> str:
    done = "\n".join(f"#   - {c}" for c in task.done_when) or "#   - (none recorded)"
    body = task.check_script.strip() or (
        'echo "No executable check was generated for this task." >&2\n'
        'echo "Write one before marking the task complete." >&2\n'
        "exit 1"
    )
    return _fill(
        CHECK_SCRIPT,
        {"ID": task.id, "TITLE": task.title, "DONE_WHEN": done, "BODY": body},
    )


# --------------------------------------------------------------------------- #
# State files
# --------------------------------------------------------------------------- #

def render_backlog_json(backlog: Backlog) -> str:
    return json.dumps(backlog.model_dump(), indent=2) + "\n"


def render_progress_json(backlog: Backlog) -> str:
    first = backlog.tasks[0].id if backlog.tasks else None
    progress = {
        "current_task": first,
        "attempts": 0,
        "completed": [],
        "blocked": [],
        "started_at": None,
        "last_verdict": None,
    }
    return json.dumps(progress, indent=2) + "\n"


DECISIONS_LOG = """# Decisions log

Append one entry per judgement call. Format:

    [<task-id>] <what you decided> — <why> — <what you rejected>

This is the memory that survives your context being reset. Write for the next
session, which will not remember this one.
"""


def render_decisions_log() -> str:
    return DECISIONS_LOG


GITIGNORE = """state/progress.json.lock
*.log.tmp
.env
.env.local
__pycache__/
node_modules/
.venv/
dist/
build/
"""


def render_gitignore() -> str:
    return GITIGNORE


# --------------------------------------------------------------------------- #
# README
# --------------------------------------------------------------------------- #

README = """# %%NAME%%

%%ONE_LINE%%

Generated by [Ouroboros](https://github.com/Anshpatel2434/Ouroboros). This is an
**agent harness repo**: the project skeleton plus the guardrails an autonomous
coding agent needs to build the rest of it without drifting.

## Start

```bash
./init.sh                      # install, wire hooks, prove the baseline is green
python runner/run_agent.py     # hand the backlog to the agent
```

`init.sh` finishes by running `./verify.sh`. If that is not green on a fresh
clone, fix it before starting the agent — the agent's whole feedback loop
depends on that command being trustworthy.

## What is here

| Path | Purpose |
|---|---|
| `CLAUDE.md` | The agent's standing orders. Read this first. |
| `spec.md` | The agreed definition of the project. Immutable to the agent. |
| `task_backlog.json` | The work, decomposed into one-commit tasks. |
| `verify.sh` | The one command that decides whether work is acceptable. |
| `checks/` | Per-task acceptance checks. |
| `state/` | Progress and the agent's decision log — its memory across sessions. |
| `.githooks/pre-commit` | Deterministic gate: protected paths and scope fences. |
| `runner/` | The loop that drives the agent through the backlog. |

## The guardrails

- **Protected paths** — %%PROTECTED%% cannot be modified by the agent. The
  pre-commit hook blocks it.
- **Scope fences** — each task declares the only paths it may touch.
- **Circuit breakers** — the runner stops on %%MAX_ATTEMPTS%% failed attempts at
  one task, after %%WALL_CLOCK%% minutes, or when it detects no progress.

## Backlog

%%TASK_TABLE%%
"""


def render_readme(spec: ProjectSpec, backlog: Backlog) -> str:
    rows = "\n".join(
        f"| `{t.id}` | {t.title} | {', '.join(f'`{p}`' for p in t.scope_paths) or '—'} |"
        for t in backlog.tasks
    )
    table = (
        "| Task | Title | Scope |\n|---|---|---|\n" + rows
        if backlog.tasks
        else "_No tasks generated._"
    )
    return _fill(
        README,
        {
            "NAME": spec.name,
            "ONE_LINE": spec.one_line,
            "PROTECTED": ", ".join(f"`{p}`" for p in spec.boundaries.protected_paths),
            "MAX_ATTEMPTS": str(spec.boundaries.max_attempts_per_task),
            "WALL_CLOCK": str(spec.boundaries.max_wall_clock_minutes),
            "TASK_TABLE": table,
        },
    )


def topology_runner_name(spec: ProjectSpec) -> str:
    return (
        "runner/run_fleet.py"
        if spec.boundaries.topology is Topology.WORKTREE_FLEET
        else "runner/run_agent.py"
    )
