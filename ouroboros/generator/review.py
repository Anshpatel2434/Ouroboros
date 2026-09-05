"""The self-review pass — the quality gate on our own output.

A critic model reads the assembled repository and reports what would break an
agent's first session. Blocking findings send the blueprint back for one
correction pass.

Known limit, stated plainly because it matters: a critic can judge whether
`verify.sh` looks right for the stack, but it cannot prove the command runs.
`structural_findings` below covers the mechanical half that judgement should
never have been asked for, and the seam is deliberately wide enough to drop
real execution checking in later.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ouroboros.generator.prompts import SELF_REVIEW
from ouroboros.llm.client import LLM
from ouroboros.models.blueprint import RepoBlueprint


class ReviewFinding(BaseModel):
    location: str = Field(description="File path or task id the finding is about.")
    issue: str
    evidence: str
    fix: str
    blocking: bool = False


class ReviewReport(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
    verdict: str = "pass"

    @property
    def blocking(self) -> list[ReviewFinding]:
        return [f for f in self.findings if f.blocking]

    @property
    def passed(self) -> bool:
        return not self.blocking

    def summary(self) -> str:
        if self.passed:
            advisory = len(self.findings)
            return f"PASS — {advisory} advisory finding(s)" if advisory else "PASS — clean"
        return f"REJECTED — {len(self.blocking)} blocking finding(s)"


def structural_findings(blueprint: RepoBlueprint) -> list[ReviewFinding]:
    """Mechanical checks on the artifact. No judgement, no model, no arguing."""
    findings: list[ReviewFinding] = []
    paths = set(blueprint.paths())

    required = ["CLAUDE.md", "spec.md", "task_backlog.json", "init.sh", "verify.sh"]
    for path in required:
        if path not in paths:
            findings.append(
                ReviewFinding(
                    location=path,
                    issue="Mandatory harness file missing.",
                    evidence=f"{path} is not in the generated repo.",
                    fix="Emit it; the file inventory is not optional.",
                    blocking=True,
                )
            )

    for task in blueprint.backlog.tasks:
        check_path = f"checks/{task.id}.sh"
        if check_path not in paths:
            findings.append(
                ReviewFinding(
                    location=task.id,
                    issue="Task has no acceptance check.",
                    evidence=f"{check_path} was not generated.",
                    fix="Generate a check script that exits non-zero until the task is done.",
                    blocking=True,
                )
            )
        if not task.scope_paths:
            findings.append(
                ReviewFinding(
                    location=task.id,
                    issue="Task has no scope fence.",
                    evidence=f"{task.id} declares no scope_paths.",
                    fix="Fence the task to the paths its component owns.",
                    blocking=True,
                )
            )
        if not task.done_when:
            findings.append(
                ReviewFinding(
                    location=task.id,
                    issue="Task has no completion condition.",
                    evidence=f"{task.id} declares no done_when.",
                    fix="State observable conditions the check script can evaluate.",
                    blocking=True,
                )
            )

    covered = {t.requirement_id for t in blueprint.backlog.tasks if t.requirement_id}
    for requirement in blueprint.spec.requirements:
        if requirement.id not in covered:
            findings.append(
                ReviewFinding(
                    location=requirement.id,
                    issue="Requirement is not delivered by any task.",
                    evidence=f"No task references {requirement.id}: {requirement.statement}",
                    fix="Add a task for it, or drop the requirement from the spec.",
                    blocking=True,
                )
            )

    # Some files are legitimately empty — a Python package marker, a directory
    # placeholder. Flagging those would train the reader to ignore the check.
    may_be_empty = {"__init__.py", "py.typed", ".gitkeep", ".gitignore", ".keep"}
    empty = [
        f.path
        for f in blueprint.files
        if not f.contents.strip() and f.path.rsplit("/", 1)[-1] not in may_be_empty
    ]
    for path in empty:
        findings.append(
            ReviewFinding(
                location=path,
                issue="Generated file is empty.",
                evidence=f"{path} has no contents.",
                fix="Generate real contents or do not emit the file.",
                blocking=True,
            )
        )

    return findings


# The structural checks already cover the mandatory inventory and the state
# files, so the critic's budget goes to what only judgement can assess: the
# commands that must run, the checks that must prove something, and the
# skeleton that must build.
_LOW_VALUE_FOR_REVIEW = (
    "state/",
    ".gitignore",
    "README.md",
    ".github/",
    "runner/",
    "spec.md",
)


def _review_priority(path: str) -> int:
    if path == "verify.sh" or path == "init.sh":
        return 0
    if path.startswith("checks/"):
        return 1
    if path == "CLAUDE.md":
        return 2
    if path.startswith(_LOW_VALUE_FOR_REVIEW):
        return 9
    return 3  # skeleton files


def _render_for_review(blueprint: RepoBlueprint, budget: int) -> str:
    """The repository as text, most review-worthy files first, inside a budget."""
    ordered = sorted(blueprint.files, key=lambda f: (_review_priority(f.path), f.path))

    chunks: list[str] = []
    remaining = budget
    for generated in ordered:
        if remaining <= 0:
            chunks.append(f"===== {generated.path} ===== [omitted, budget exhausted]")
            continue
        allowance = min(len(generated.contents), max(300, remaining // 3))
        body = generated.contents[:allowance]
        if allowance < len(generated.contents):
            body += "\n... [truncated]"
        chunks.append(f"===== {generated.path} =====\n{body}")
        remaining -= allowance

    return "\n\n".join(chunks)


def _backlog_digest(blueprint: RepoBlueprint) -> str:
    """The backlog as compact lines rather than JSON, which triples the tokens."""
    lines = []
    for task in blueprint.backlog.tasks:
        lines.append(
            f"{task.id} [{task.requirement_id or 'no requirement'}] {task.title}\n"
            f"  scope: {', '.join(task.scope_paths) or 'NONE'}\n"
            f"  done_when: {'; '.join(task.done_when) or 'NONE'}\n"
            f"  depends_on: {', '.join(task.depends_on) or 'none'}"
        )
    return "\n".join(lines) or "(empty backlog)"


def _spec_digest(blueprint: RepoBlueprint) -> str:
    spec = blueprint.spec
    requirements = "\n".join(
        f"  {r.id}: {r.statement} | accepted when: {'; '.join(r.acceptance_criteria)}"
        for r in spec.requirements
    )
    return (
        f"{spec.name} — {spec.one_line}\n"
        f"stack: {spec.stack.language} {spec.stack.language_version}, "
        f"{spec.stack.framework or 'no framework'}, {spec.stack.package_manager}\n"
        f"verification: {', '.join(f'{k}={v}' for k, v in spec.verification.commands())}\n"
        f"non-goals: {'; '.join(spec.non_goals) or 'none'}\n"
        f"requirements:\n{requirements}"
    )


def self_review(llm: LLM, blueprint: RepoBlueprint) -> ReviewReport:
    """Structural checks first, then the critic on what survives."""
    from ouroboros.llm.client import context_chars

    structural = structural_findings(blueprint)

    report = llm.structured(
        ReviewReport,
        system=SELF_REVIEW,
        user=(
            f"Specification:\n{_spec_digest(blueprint)}\n\n"
            f"Backlog:\n{_backlog_digest(blueprint)}\n\n"
            f"Generated repository:\n"
            + _render_for_review(blueprint, context_chars("review"))
        ),
        role="review",
    )

    combined = structural + report.findings
    return ReviewReport(
        findings=combined,
        verdict="pass" if not any(f.blocking for f in combined) else "rejected",
    )
