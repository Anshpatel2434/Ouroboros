"""The runner scripts emitted into every generated repo.

Stdlib-only Python on purpose: the generated project may be Node, Go or Rust,
and the runner must not drag a dependency tree into a repo that has its own.

These are the loop boundaries made real — attempts, wall clock, cost, scope, and
the no-progress detector that catches an agent thrashing without failing.
"""

from __future__ import annotations

from ouroboros.models.spec import ProjectSpec

RUN_AGENT = '''#!/usr/bin/env python3
"""Drive the coding agent through the backlog, one task per commit.

Run with: python runner/run_agent.py [--task TASK_ID] [--dry-run]

The loop is deliberately boring: pick the next unblocked task, hand it to the
agent with a fresh context, verify the result mechanically, commit if green,
move on. Everything interesting is in the circuit breakers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG_PATH = ROOT / "task_backlog.json"
PROGRESS_PATH = ROOT / "state" / "progress.json"
DECISIONS_PATH = ROOT / "state" / "decisions.log"

MAX_ATTEMPTS = %%MAX_ATTEMPTS%%
WALL_CLOCK_MINUTES = %%WALL_CLOCK%%
MAX_COST_USD = %%MAX_COST%%

AGENT_CMD = os.environ.get("OUROBOROS_AGENT_CMD", "claude")
AGENT_ARGS = os.environ.get("OUROBOROS_AGENT_ARGS", "--permission-mode acceptEdits").split()


def load(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\\n", encoding="utf-8")


def log(message):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = "[" + stamp + "] " + message
    print(line, flush=True)
    with DECISIONS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\\n")


def git(*args, capture=True):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=capture, text=True, check=False
    )


def fingerprint():
    """A cheap signature of the working tree, for detecting thrash."""
    head = git("rev-parse", "HEAD").stdout.strip()
    diff = git("diff", "HEAD").stdout
    return head + ":" + str(hash(diff))


def next_task(backlog, progress):
    completed = set(progress.get("completed", []))
    blocked = set(progress.get("blocked", []))
    for task in backlog.get("tasks", []):
        if task["id"] in completed or task["id"] in blocked:
            continue
        if all(dep in completed for dep in task.get("depends_on", [])):
            return task
    return None


def build_prompt(task):
    scope = "\\n".join("  - " + p for p in task.get("scope_paths", [])) or "  - (unfenced)"
    done = "\\n".join("  - " + c for c in task.get("done_when", [])) or "  - (none recorded)"
    return (
        "Read CLAUDE.md first; it is your standing order.\\n\\n"
        "Active task: " + task["id"] + " — " + task["title"] + "\\n\\n"
        "Intent:\\n" + task.get("intent", "") + "\\n\\n"
        "You may only modify these paths:\\n" + scope + "\\n\\n"
        "This task is done when:\\n" + done + "\\n\\n"
        "Before you finish: run ./verify.sh and ./checks/" + task["id"] + ".sh. "
        "Both must exit 0. Do not weaken a test to get there. Do not touch any "
        "protected path. When green, commit with the task id in the message."
    )


def run_agent(prompt, dry_run=False):
    if dry_run:
        print("--- prompt ---")
        print(prompt)
        return 0
    result = subprocess.run([AGENT_CMD, "-p", prompt, *AGENT_ARGS], cwd=ROOT, check=False)
    return result.returncode


def run_script(path):
    if not path.exists():
        return 1, "missing script: " + str(path)
    result = subprocess.run(["bash", str(path)], cwd=ROOT, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr)[-4000:]


def verify(task):
    code, output = run_script(ROOT / "verify.sh")
    if code != 0:
        return False, "verify.sh failed:\\n" + output
    code, output = run_script(ROOT / "checks" / (task["id"] + ".sh"))
    if code != 0:
        return False, "acceptance check failed:\\n" + output
    return True, "green"


def commit_if_needed(task):
    if not git("status", "--porcelain").stdout.strip():
        return
    git("add", "-A")
    git("commit", "-m", task["id"] + ": " + task["title"], capture=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", help="Run only this task id.")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts, run nothing.")
    args = parser.parse_args()

    backlog = load(BACKLOG_PATH, {"tasks": []})
    progress = load(PROGRESS_PATH, {"completed": [], "blocked": [], "attempts": 0})
    progress.setdefault("completed", [])
    progress.setdefault("blocked", [])

    started = time.time()
    progress["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    last_fingerprint = None
    stagnant_rounds = 0

    while True:
        elapsed_minutes = (time.time() - started) / 60
        if elapsed_minutes > WALL_CLOCK_MINUTES:
            log("BREAKER wall-clock: stopping after %.0f minutes." % elapsed_minutes)
            break

        task = next_task(backlog, progress) if not args.task else next(
            (t for t in backlog["tasks"] if t["id"] == args.task), None
        )
        if task is None:
            log("No runnable tasks left.")
            break

        progress["current_task"] = task["id"]
        save(PROGRESS_PATH, progress)

        attempts = 0
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            log("task " + task["id"] + " attempt " + str(attempts))

            exit_code = run_agent(build_prompt(task), dry_run=args.dry_run)
            if args.dry_run:
                return 0
            if exit_code != 0:
                log("agent exited " + str(exit_code))

            ok, detail = verify(task)
            progress["last_verdict"] = {"task": task["id"], "ok": ok, "detail": detail[:500]}

            if ok:
                commit_if_needed(task)
                progress["completed"].append(task["id"])
                progress["attempts"] = 0
                log("task " + task["id"] + " complete")
                break

            log("task " + task["id"] + " not accepted: " + detail.splitlines()[0])

            current = fingerprint()
            if current == last_fingerprint:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            last_fingerprint = current

            if stagnant_rounds >= 2:
                log("BREAKER no-progress: the working tree stopped changing. Stopping.")
                save(PROGRESS_PATH, progress)
                return 2
        else:
            progress["blocked"].append(task["id"])
            log(
                "BREAKER attempts: " + task["id"] + " blocked after "
                + str(MAX_ATTEMPTS) + " attempts. Moving on."
            )

        progress["attempts"] = 0
        save(PROGRESS_PATH, progress)

        if args.task:
            break

    save(PROGRESS_PATH, progress)
    remaining = [
        t["id"]
        for t in backlog.get("tasks", [])
        if t["id"] not in progress["completed"] and t["id"] not in progress["blocked"]
    ]
    log("done. completed=" + str(len(progress["completed"]))
        + " blocked=" + str(len(progress["blocked"]))
        + " remaining=" + str(len(remaining)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


RUN_FLEET = '''#!/usr/bin/env python3
"""Run independent backlog tasks in parallel, one git worktree per agent.

Run with: python runner/run_fleet.py [--workers N]

Only tasks whose dependencies are already complete and whose scope fences do not
overlap are dispatched together; anything else waits for the next wave. A task
is merged back only after its own checks pass inside its worktree.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKTREE_DIR = ROOT / ".worktrees"
BACKLOG_PATH = ROOT / "task_backlog.json"
PROGRESS_PATH = ROOT / "state" / "progress.json"
DECISIONS_PATH = ROOT / "state" / "decisions.log"

MAX_ATTEMPTS = %%MAX_ATTEMPTS%%
DEFAULT_WORKERS = 3

import os

AGENT_CMD = os.environ.get("OUROBOROS_AGENT_CMD", "claude")
AGENT_ARGS = os.environ.get("OUROBOROS_AGENT_ARGS", "--permission-mode acceptEdits").split()


def log(message):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = "[" + stamp + "] " + message
    print(line, flush=True)
    with DECISIONS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\\n")


def load(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\\n", encoding="utf-8")


def git(*args, cwd=None, capture=True):
    return subprocess.run(
        ["git", *args], cwd=cwd or ROOT, capture_output=capture, text=True, check=False
    )


def overlaps(a, b):
    for x in a:
        for y in b:
            if x.startswith(y) or y.startswith(x):
                return True
    return False


def wave(backlog, progress):
    """The next batch of tasks that can safely run at the same time."""
    completed = set(progress.get("completed", []))
    blocked = set(progress.get("blocked", []))
    chosen = []
    for task in backlog.get("tasks", []):
        if task["id"] in completed or task["id"] in blocked:
            continue
        if not all(dep in completed for dep in task.get("depends_on", [])):
            continue
        scope = task.get("scope_paths", [])
        if any(overlaps(scope, other.get("scope_paths", [])) for other in chosen):
            continue
        chosen.append(task)
    return chosen


def build_prompt(task):
    scope = "\\n".join("  - " + p for p in task.get("scope_paths", [])) or "  - (unfenced)"
    done = "\\n".join("  - " + c for c in task.get("done_when", [])) or "  - (none recorded)"
    return (
        "Read CLAUDE.md first; it is your standing order.\\n\\n"
        "Active task: " + task["id"] + " — " + task["title"] + "\\n\\n"
        "Intent:\\n" + task.get("intent", "") + "\\n\\n"
        "You may only modify these paths:\\n" + scope + "\\n\\n"
        "This task is done when:\\n" + done + "\\n\\n"
        "Run ./verify.sh and ./checks/" + task["id"] + ".sh before finishing; both "
        "must exit 0. Commit with the task id in the message."
    )


def run_task(task):
    """Run one task in its own worktree. Returns (task_id, ok, detail)."""
    branch = "task/" + task["id"]
    path = WORKTREE_DIR / task["id"]

    if path.exists():
        git("worktree", "remove", "--force", str(path))
    result = git("worktree", "add", "-b", branch, str(path), "HEAD")
    if result.returncode != 0:
        return task["id"], False, "could not create worktree: " + result.stderr

    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            log(task["id"] + " attempt " + str(attempt) + " in " + str(path))
            subprocess.run(
                [AGENT_CMD, "-p", build_prompt(task), *AGENT_ARGS],
                cwd=path,
                check=False,
            )

            verify = subprocess.run(
                ["bash", "verify.sh"], cwd=path, capture_output=True, text=True
            )
            check = subprocess.run(
                ["bash", "checks/" + task["id"] + ".sh"], cwd=path, capture_output=True, text=True
            )
            if verify.returncode == 0 and check.returncode == 0:
                if subprocess.run(
                    ["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True
                ).stdout.strip():
                    git("add", "-A", cwd=path)
                    git("commit", "-m", task["id"] + ": " + task["title"], cwd=path)
                return task["id"], True, "green"

        return task["id"], False, (verify.stdout + verify.stderr + check.stdout + check.stderr)[-1500:]
    finally:
        pass


def merge(task_id):
    result = git("merge", "--no-ff", "-m", "merge " + task_id, "task/" + task_id)
    return result.returncode == 0, result.stdout + result.stderr


def cleanup(task_id):
    path = WORKTREE_DIR / task_id
    git("worktree", "remove", "--force", str(path))
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()

    backlog = load(BACKLOG_PATH, {"tasks": []})
    progress = load(PROGRESS_PATH, {"completed": [], "blocked": []})
    progress.setdefault("completed", [])
    progress.setdefault("blocked", [])
    WORKTREE_DIR.mkdir(exist_ok=True)

    while True:
        batch = wave(backlog, progress)
        if not batch:
            break

        log("dispatching " + str(len(batch)) + " task(s): " + ", ".join(t["id"] for t in batch))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(run_task, batch))

        progressed = False
        for task_id, ok, detail in results:
            if ok:
                merged, output = merge(task_id)
                if merged:
                    progress["completed"].append(task_id)
                    progressed = True
                    log(task_id + " merged")
                else:
                    progress["blocked"].append(task_id)
                    log(task_id + " passed its checks but would not merge: " + output[:300])
            else:
                progress["blocked"].append(task_id)
                log(task_id + " blocked: " + detail.splitlines()[0] if detail else task_id + " blocked")
            cleanup(task_id)

        save(PROGRESS_PATH, progress)
        if not progressed:
            log("BREAKER no-progress: a full wave produced nothing mergeable. Stopping.")
            return 2

    log("done. completed=" + str(len(progress["completed"]))
        + " blocked=" + str(len(progress["blocked"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def render_runner(spec: ProjectSpec) -> str:
    from ouroboros.models.spec import Topology

    template = (
        RUN_FLEET if spec.boundaries.topology is Topology.WORKTREE_FLEET else RUN_AGENT
    )
    cost = (
        str(spec.boundaries.max_cost_usd)
        if spec.boundaries.max_cost_usd is not None
        else "None"
    )
    return (
        template.replace("%%MAX_ATTEMPTS%%", str(spec.boundaries.max_attempts_per_task))
        .replace("%%WALL_CLOCK%%", str(spec.boundaries.max_wall_clock_minutes))
        .replace("%%MAX_COST%%", cost)
    )
