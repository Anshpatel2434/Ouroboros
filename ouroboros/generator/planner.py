"""The thinking half of generation: what work to do, and what floor to stand on.

Two LLM calls, both grounded in the corpus. Everything else the Generator does
is deterministic rendering — which is deliberate, because a template that always
produces the same guardrails is a feature, not a limitation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.generator.prompts import BACKLOG_PLANNER, SKELETON_PLANNER
from ouroboros.inquisitor.research import SkeletonFile, find_playbook
from ouroboros.llm.client import LLM, context_chars
from ouroboros.models.blueprint import Backlog, Task
from ouroboros.models.spec import ProjectSpec


class SkeletonPlan(BaseModel):
    files: list[SkeletonFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _stack_context(
    retriever: FileCorpusRetriever, spec: ProjectSpec, role: str = "default"
) -> str:
    """Whatever the corpus knows about this stack, sized to the prompt budget."""
    budget = context_chars(role)

    playbook = find_playbook(retriever, spec.stack)
    if playbook is not None:
        return playbook.key_knowledge[:budget]

    query = f"{spec.stack.language} {spec.stack.framework or ''} {spec.stack.package_manager} test lint"
    hits = retriever.search(query, limit=3)
    if not hits:
        return "No corpus coverage for this stack."

    per_hit = max(400, budget // len(hits))
    return "\n\n".join(
        f"### {h.document.title}\n{h.document.key_knowledge[:per_hit]}" for h in hits
    )


def _spec_context(spec: ProjectSpec) -> str:
    return spec.model_dump_json(indent=2)


def _feedback_block(feedback: str) -> str:
    """Review findings from a rejected attempt, fed back for the correction pass."""
    if not feedback.strip():
        return ""
    return (
        "\n\nA previous attempt was rejected by review. Fix exactly these findings "
        "and change nothing else:\n" + feedback
    )


def plan_backlog(
    llm: LLM, retriever: FileCorpusRetriever, spec: ProjectSpec, feedback: str = ""
) -> Backlog:
    """Decompose the spec into one-commit tasks with real acceptance checks."""
    component_map = "\n".join(
        f"- {c.name}: owns {', '.join(c.paths)} — {c.responsibility}" for c in spec.components
    )
    backlog = llm.structured(
        Backlog,
        system=BACKLOG_PLANNER,
        user=(
            f"Specification:\n{_spec_context(spec)}\n\n"
            f"Components and the paths they own (use these for scope fences):\n{component_map}\n\n"
            f"Verification available to every check script:\n"
            + "\n".join(f"- {label}: {cmd}" for label, cmd in spec.verification.commands())
            + f"\n\nStack knowledge:\n{_stack_context(retriever, spec, 'backlog')}"
            + _feedback_block(feedback)
        ),
        role="backlog",
    )
    return _normalize_backlog(backlog, spec)


def _clean_check_script(body: str) -> str:
    """Make a model-written check body safe to drop into our script template.

    Live runs produced check scripts with a literal backslash-n instead of real
    newlines, and with their own shebang and `set -euo pipefail` on top of the
    ones the template already supplies — a duplicate shebang mid-file is a
    syntax error, so the check could never run.
    """
    if not body:
        return ""

    script = body.strip()

    # A body that is one long line of escaped newlines is unrunnable as-is.
    if "\\n" in script and "\n" not in script.strip():
        script = script.replace("\\n", "\n")
    script = script.replace("\r\n", "\n")

    lines = script.split("\n")
    while lines:
        head = lines[0].strip()
        if (
            head.startswith("#!")
            or head.startswith("set -e")
            or head.startswith("set -u")
            or not head
        ):
            lines.pop(0)
            continue
        break

    return "\n".join(lines).strip()


def _normalize_backlog(backlog: Backlog, spec: ProjectSpec) -> Backlog:
    """Repair what the model reliably gets slightly wrong, deterministically.

    Ids are renumbered so they are unique and ordered, dependencies pointing at
    nothing are dropped rather than left to break the runner, and a task with no
    fence inherits its component's paths instead of being allowed to roam.
    """
    tasks: list[Task] = []
    seen: set[str] = set()
    all_component_paths = [p for c in spec.components for p in c.paths]

    for index, task in enumerate(backlog.tasks, start=1):
        task_id = task.id.strip() or f"T-{index:03d}"
        if task_id in seen:
            task_id = f"T-{index:03d}"
        seen.add(task_id)

        scope = [p for p in task.scope_paths if p.strip()] or all_component_paths
        tasks.append(
            task.model_copy(
                update={
                    "id": task_id,
                    "scope_paths": scope,
                    "check_script": _clean_check_script(task.check_script),
                    "status": "pending",
                    "attempts": 0,
                }
            )
        )

    known = {t.id for t in tasks}
    for task in tasks:
        task.depends_on = [d for d in task.depends_on if d in known and d != task.id]

    return Backlog(tasks=tasks)


def plan_skeleton(
    llm: LLM, retriever: FileCorpusRetriever, spec: ProjectSpec, feedback: str = ""
) -> SkeletonPlan:
    """Produce a minimal project that already passes its own test command."""
    component_map = "\n".join(
        f"- {c.name}: {', '.join(c.paths)} — {c.responsibility}" for c in spec.components
    )
    return llm.structured(
        SkeletonPlan,
        system=SKELETON_PLANNER,
        user=(
            f"Stack: {spec.stack.language} {spec.stack.language_version}, "
            f"framework {spec.stack.framework or 'none'}, "
            f"package manager {spec.stack.package_manager}.\n\n"
            f"Verification commands that must pass on the bare skeleton:\n"
            + "\n".join(f"- {label}: {cmd}" for label, cmd in spec.verification.commands())
            + f"\n\nComponents needing a home:\n{component_map}\n\n"
            f"Project: {spec.name} — {spec.one_line}\n\n"
            f"Stack knowledge:\n{_stack_context(retriever, spec, 'skeleton')}"
            + _feedback_block(feedback)
        ),
        role="skeleton",
    )
