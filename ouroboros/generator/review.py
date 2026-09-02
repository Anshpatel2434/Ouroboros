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


def _render_for_review(blueprint: RepoBlueprint, budget: int = 60_000) -> str:
    """The repository as text, truncated per-file so no single file eats the budget."""
    per_file = max(1200, budget // max(len(blueprint.files), 1))
    chunks = []
    for generated in blueprint.files:
        body = generated.contents
        if len(body) > per_file:
            body = body[:per_file] + "\n... [truncated for review]"
        chunks.append(f"===== {generated.path} =====\n{body}")
    return "\n\n".join(chunks)


def self_review(llm: LLM, blueprint: RepoBlueprint) -> ReviewReport:
    """Structural checks first, then the critic on what survives."""
    structural = structural_findings(blueprint)

    report = llm.structured(
        ReviewReport,
        system=SELF_REVIEW,
        user=(
            f"Specification:\n{blueprint.spec.model_dump_json(indent=2)}\n\n"
            f"Backlog:\n{blueprint.backlog.model_dump_json(indent=2)}\n\n"
            f"Generated repository:\n{_render_for_review(blueprint)}"
        ),
    )

    combined = structural + report.findings
    return ReviewReport(
        findings=combined,
        verdict="pass" if not any(f.blocking for f in combined) else "rejected",
    )
