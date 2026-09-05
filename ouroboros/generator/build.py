"""Assembling, reviewing, and emitting a harness repo.

Generation is a plain sequential pipeline rather than a graph: plan, assemble,
review, correct once, emit. The evaluator-optimizer loop here has exactly one
feedback edge and a hard attempt cap, and expressing that as a graph would add
machinery without adding behaviour.

Nothing touches the filesystem until a blueprint has passed review, so a
rejected generation never leaves half a repository behind.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.generator import templates as tpl
from ouroboros.generator.planner import SkeletonPlan, plan_backlog, plan_skeleton
from ouroboros.generator.review import ReviewReport, self_review
from ouroboros.generator.runner_templates import render_runner
from ouroboros.llm.client import LLM, critic_llm, default_llm
from ouroboros.models.blueprint import Backlog, GeneratedFile, RepoBlueprint
from ouroboros.models.spec import ProjectSpec, Topology

MAX_GENERATION_ATTEMPTS = 2


@dataclass
class GeneratorDeps:
    llm: LLM = field(default_factory=default_llm)
    critic: LLM = field(default_factory=critic_llm)
    retriever: FileCorpusRetriever = field(default_factory=FileCorpusRetriever)
    max_attempts: int = MAX_GENERATION_ATTEMPTS


class GenerationResult(BaseModel):
    blueprint: RepoBlueprint
    review: ReviewReport
    attempts: int

    @property
    def accepted(self) -> bool:
        return self.review.passed


def assemble(spec: ProjectSpec, backlog: Backlog, skeleton: SkeletonPlan) -> RepoBlueprint:
    """Build the complete file set. Deterministic: same inputs, same repo."""
    runner_path = tpl.topology_runner_name(spec)

    files: list[GeneratedFile] = [
        GeneratedFile(path="CLAUDE.md", contents=tpl.render_claude_md(spec)),
        GeneratedFile(path="spec.md", contents=tpl.render_spec_md(spec)),
        GeneratedFile(path="README.md", contents=tpl.render_readme(spec, backlog)),
        GeneratedFile(path="task_backlog.json", contents=tpl.render_backlog_json(backlog)),
        GeneratedFile(path="verify.sh", contents=tpl.render_verify_sh(spec), executable=True),
        GeneratedFile(path="init.sh", contents=tpl.render_init_sh(spec), executable=True),
        GeneratedFile(
            path=".githooks/pre-commit",
            contents=tpl.render_pre_commit(spec),
            executable=True,
        ),
        GeneratedFile(path=".github/workflows/verify.yml", contents=tpl.render_workflow()),
        GeneratedFile(path="state/progress.json", contents=tpl.render_progress_json(backlog)),
        GeneratedFile(path="state/decisions.log", contents=tpl.render_decisions_log()),
        GeneratedFile(path=".gitignore", contents=tpl.render_gitignore()),
        GeneratedFile(path=runner_path, contents=render_runner(spec), executable=True),
    ]

    files += [
        GeneratedFile(
            path=f"checks/{task.id}.sh",
            contents=tpl.render_check_script(task),
            executable=True,
        )
        for task in backlog.tasks
    ]

    # Skeleton files last so a stack playbook can never overwrite a guardrail.
    reserved = {f.path for f in files}
    protected_prefixes = ("checks/", "state/", ".githooks/")
    for skeleton_file in skeleton.files:
        path = skeleton_file.path.lstrip("./")
        if path in reserved or path.startswith(protected_prefixes):
            continue
        files.append(GeneratedFile(path=path, contents=skeleton_file.contents))

    notes = list(skeleton.notes)
    if spec.boundaries.topology is Topology.WORKTREE_FLEET:
        notes.append("Parallel topology: tasks run in isolated git worktrees.")

    return RepoBlueprint(spec=spec, backlog=backlog, files=files, notes=notes)


HARNESS_PATHS = (
    "CLAUDE.md",
    "spec.md",
    "README.md",
    "verify.sh",
    "init.sh",
    "task_backlog.json",
    ".gitignore",
    ".githooks/",
    ".github/",
    "state/",
    "runner/",
    "checks/",
)


def _classify_feedback(
    review: ReviewReport, blueprint: RepoBlueprint
) -> tuple[str, str, list[str]]:
    """Route review findings to whoever can actually act on them.

    A live run taught this the hard way: findings about a malformed pre-commit
    hook were fed back to the backlog planner, which dutifully produced a
    backlog of tasks to repair the harness instead of building the project.

    Findings about tasks or requirements are the planner's. Findings about
    skeleton files are the skeleton planner's. Findings about rendered harness
    files belong to neither — those are bugs in our templates, and are returned
    for reporting rather than fed to a model that cannot fix them.
    """
    task_ids = blueprint.backlog.ids()
    requirement_ids = blueprint.spec.requirement_ids()

    plan: list[str] = []
    skeleton: list[str] = []
    template: list[str] = []

    for finding in review.blocking:
        line = f"- [{finding.location}] {finding.issue} | evidence: {finding.evidence} | fix: {finding.fix}"
        location = finding.location.strip()

        if location in task_ids or location in requirement_ids or location == "backlog":
            plan.append(line)
        elif location.startswith(HARNESS_PATHS):
            template.append(line)
        else:
            skeleton.append(line)

    return "\n".join(plan), "\n".join(skeleton), template


def _feedback(review: ReviewReport) -> str:
    return "\n".join(
        f"- [{f.location}] {f.issue} | evidence: {f.evidence} | fix: {f.fix}"
        for f in review.blocking
    )


def generate(spec: ProjectSpec, deps: GeneratorDeps | None = None) -> GenerationResult:
    """Plan, assemble, review, and correct once if the critic refuses."""
    deps = deps or GeneratorDeps()

    plan_feedback = ""
    skeleton_feedback = ""
    template_problems: list[str] = []
    review: ReviewReport | None = None
    blueprint: RepoBlueprint | None = None

    for attempt in range(1, deps.max_attempts + 1):
        backlog = plan_backlog(deps.llm, deps.retriever, spec, feedback=plan_feedback)
        skeleton = plan_skeleton(
            deps.llm, deps.retriever, spec, feedback=skeleton_feedback
        )
        blueprint = assemble(spec, backlog, skeleton)
        review = self_review(deps.critic, blueprint)

        if review.passed:
            return GenerationResult(blueprint=blueprint, review=review, attempts=attempt)

        plan_feedback, skeleton_feedback, template_problems = _classify_feedback(
            review, blueprint
        )

    # Still rejected. Hand back the artifact and the reasons rather than
    # pretending success: the findings are what the developer needs to see.
    blueprint.notes.append(
        "Generation was not accepted by review. The findings below are unresolved."
    )
    if template_problems:
        blueprint.notes.append(
            f"{len(template_problems)} finding(s) concern generated harness files "
            "rather than the plan. Those indicate a bug in Ouroboros itself, not "
            "in this project's spec."
        )
    return GenerationResult(blueprint=blueprint, review=review, attempts=deps.max_attempts)


def emit(blueprint: RepoBlueprint, destination: Path) -> list[Path]:
    """Write the blueprint to disk. Returns every path written."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for generated in blueprint.files:
        target = destination / generated.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.contents, encoding="utf-8", newline="\n")
        if generated.executable:
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(target)

    return written
