"""Generation: planning, assembly, self-review, and emission."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.generator.build import GeneratorDeps, assemble, emit, generate
from ouroboros.generator.planner import SkeletonPlan, _normalize_backlog
from ouroboros.generator.review import ReviewFinding, ReviewReport, structural_findings
from ouroboros.inquisitor.research import SkeletonFile
from ouroboros.models.blueprint import Backlog, Task
from ouroboros.models.spec import (
    Component,
    LoopBoundaries,
    ProjectSpec,
    Requirement,
    StackProfile,
    Topology,
    VerificationPlan,
)
from tests.fakes import FakeLLM

BASH = shutil.which("bash")


def spec(**overrides) -> ProjectSpec:
    base = dict(
        name="Invoice Tracker",
        slug="invoice-tracker",
        one_line="Tracks freelance invoices and flags overdue ones.",
        problem="Freelancers lose money chasing invoices they forget about.",
        success_criteria=["An invoice past its due date shows as overdue."],
        non_goals=["No payment processing."],
        stack=StackProfile(
            language="Python",
            language_version="3.12",
            package_manager="uv",
            corpus_covered=True,
        ),
        verification=VerificationPlan(install="echo install", test="echo test", smoke="echo smoke"),
        components=[Component(name="api", responsibility="HTTP layer.", paths=["app/"])],
        requirements=[
            Requirement(
                id="R-001",
                statement="Record an invoice.",
                acceptance_criteria=["POST /invoices returns status 201."],
            )
        ],
        glossary={"Overdue": "Past its due date and unpaid."},
    )
    base.update(overrides)
    return ProjectSpec(**base)


def backlog() -> Backlog:
    return Backlog(
        tasks=[
            Task(
                id="T-001",
                title="Add the invoice model",
                requirement_id="R-001",
                intent="Create the Invoice model with a due date.",
                scope_paths=["app/"],
                done_when=["POST /invoices returns 201."],
                check_script="echo checking && exit 0",
            )
        ]
    )


def skeleton() -> SkeletonPlan:
    return SkeletonPlan(
        files=[
            SkeletonFile(path="app/__init__.py", purpose="Package root.", contents=""" """),
            SkeletonFile(
                path="tests/test_smoke.py",
                purpose="Green baseline.",
                contents="def test_imports():\n    import app\n    assert app is not None\n",
            ),
        ],
        notes=["Skeleton passes its own tests before any feature exists."],
    )


def clean_review() -> ReviewReport:
    return ReviewReport(findings=[], verdict="pass")


def deps(llm, critic=None) -> GeneratorDeps:
    return GeneratorDeps(
        llm=llm, critic=critic or llm, retriever=FileCorpusRetriever(), max_attempts=2
    )


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def test_assemble_emits_the_mandatory_inventory():
    blueprint = assemble(spec(), backlog(), skeleton())
    paths = set(blueprint.paths())

    for required in (
        "CLAUDE.md",
        "spec.md",
        "task_backlog.json",
        "init.sh",
        "verify.sh",
        "checks/T-001.sh",
        "state/progress.json",
        "state/decisions.log",
        ".githooks/pre-commit",
        ".github/workflows/verify.yml",
        "runner/run_agent.py",
    ):
        assert required in paths, f"{required} missing from the generated repo"


def test_worktree_topology_emits_the_fleet_runner():
    fleet = spec(boundaries=LoopBoundaries(topology=Topology.WORKTREE_FLEET))
    paths = set(assemble(fleet, backlog(), skeleton()).paths())
    assert "runner/run_fleet.py" in paths
    assert "runner/run_agent.py" not in paths


def test_claude_md_carries_the_guardrails():
    blueprint = assemble(spec(), backlog(), skeleton())
    claude = blueprint.file("CLAUDE.md").contents

    assert "OUROBOROS:DYNAMIC-DIRECTIVES:START" in claude
    assert "Never weaken a test" in claude
    assert "No payment processing." in claude, "non-goals must reach the agent"
    assert "`CLAUDE.md`" in claude, "protected paths must be named"


def test_skeleton_cannot_overwrite_a_guardrail():
    """A stack playbook must never be able to replace the harness files."""
    hostile = SkeletonPlan(
        files=[
            SkeletonFile(path="verify.sh", purpose="hijack", contents="exit 0"),
            SkeletonFile(path="checks/T-001.sh", purpose="hijack", contents="exit 0"),
            SkeletonFile(path="app/main.py", purpose="legit", contents="x = 1\n"),
        ]
    )
    blueprint = assemble(spec(), backlog(), hostile)

    assert "echo test" in blueprint.file("verify.sh").contents
    assert blueprint.file("checks/T-001.sh").contents.startswith("#!/usr/bin/env bash")
    assert blueprint.file("app/main.py") is not None
    assert len([p for p in blueprint.paths() if p == "verify.sh"]) == 1


def test_backlog_json_is_valid_and_ordered():
    blueprint = assemble(spec(), backlog(), skeleton())
    parsed = json.loads(blueprint.file("task_backlog.json").contents)
    assert parsed["tasks"][0]["id"] == "T-001"
    assert parsed["tasks"][0]["scope_paths"] == ["app/"]

    progress = json.loads(blueprint.file("state/progress.json").contents)
    assert progress["current_task"] == "T-001"
    assert progress["completed"] == []


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

def test_normalize_repairs_ids_dependencies_and_fences():
    messy = Backlog(
        tasks=[
            Task(id="T-001", title="First", intent="x", scope_paths=["app/"]),
            Task(id="T-001", title="Duplicate id", intent="y", scope_paths=[]),
            Task(id="T-003", title="Bad dep", intent="z", scope_paths=["app/"], depends_on=["T-999", "T-003"]),
        ]
    )
    fixed = _normalize_backlog(messy, spec())

    assert len(fixed.ids()) == 3, "duplicate ids must be renumbered, not dropped"
    assert fixed.tasks[1].scope_paths == ["app/"], "a fenceless task inherits component paths"
    assert fixed.tasks[2].depends_on == [], "dangling and self dependencies are dropped"


# --------------------------------------------------------------------------- #
# Review
# --------------------------------------------------------------------------- #

def test_structural_review_catches_an_undelivered_requirement():
    orphan = spec(
        requirements=[
            Requirement(id="R-001", statement="Record an invoice.", acceptance_criteria=["201."]),
            Requirement(id="R-002", statement="Email a reminder.", acceptance_criteria=["Sent."]),
        ]
    )
    findings = structural_findings(assemble(orphan, backlog(), skeleton()))
    codes = {(f.location, f.blocking) for f in findings}
    assert ("R-002", True) in codes


def test_structural_review_catches_a_fenceless_task():
    unfenced = Backlog(
        tasks=[Task(id="T-001", title="No fence", intent="x", done_when=["y"], requirement_id="R-001")]
    )
    findings = structural_findings(assemble(spec(), unfenced, skeleton()))
    assert any(f.issue == "Task has no scope fence." and f.blocking for f in findings)


def test_generation_retries_once_when_review_rejects():
    rejection = ReviewReport(
        findings=[
            ReviewFinding(
                location="T-001",
                issue="Check does not prove the condition.",
                evidence="It greps for a function name.",
                fix="Run the project's tests instead.",
                blocking=True,
            )
        ],
        verdict="rejected",
    )
    llm = FakeLLM(
        {
            Backlog: [backlog()],
            SkeletonPlan: [skeleton()],
            ReviewReport: [rejection, clean_review()],
        }
    )
    result = generate(spec(), deps(llm))

    assert result.attempts == 2
    assert result.accepted
    assert llm.count(Backlog) == 2, "the correction pass must replan"

    replan_prompt = [u for s, u in llm.calls if s is Backlog][1]
    assert "rejected by review" in replan_prompt, "findings must be fed back"


def test_persistent_rejection_returns_the_findings_rather_than_claiming_success():
    rejection = ReviewReport(
        findings=[
            ReviewFinding(
                location="verify.sh",
                issue="Command not available on this stack.",
                evidence="uses a tool the skeleton never installs",
                fix="Use the package manager's own runner.",
                blocking=True,
            )
        ],
        verdict="rejected",
    )
    llm = FakeLLM(
        {Backlog: [backlog()], SkeletonPlan: [skeleton()], ReviewReport: [rejection]}
    )
    result = generate(spec(), deps(llm))

    assert not result.accepted
    assert result.attempts == 2
    assert any("not accepted by review" in n for n in result.blueprint.notes)


# --------------------------------------------------------------------------- #
# Emission
# --------------------------------------------------------------------------- #

def test_emit_writes_every_file(tmp_path):
    blueprint = assemble(spec(), backlog(), skeleton())
    written = emit(blueprint, tmp_path)

    assert len(written) == len(blueprint.files)
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "checks" / "T-001.sh").exists()
    assert (tmp_path / ".githooks" / "pre-commit").exists()


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
def test_generated_verify_script_actually_runs(tmp_path):
    """Our own suite executes what we generate, even though the product's gate does not."""
    emit(assemble(spec(), backlog(), skeleton()), tmp_path)
    result = subprocess.run(
        [BASH, "verify.sh"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all checks passed" in result.stdout


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
def test_generated_check_script_actually_runs(tmp_path):
    emit(assemble(spec(), backlog(), skeleton()), tmp_path)
    result = subprocess.run(
        [BASH, "checks/T-001.sh"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
def test_pre_commit_hook_blocks_a_protected_path(tmp_path):
    """The agent must not be able to edit its own guardrails (D17)."""
    emit(assemble(spec(), backlog(), skeleton()), tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "CLAUDE.md"], cwd=tmp_path, check=True)

    result = subprocess.run(
        [BASH, ".githooks/pre-commit"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "protected harness path" in result.stdout


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
def test_pre_commit_hook_allows_an_in_scope_change(tmp_path):
    emit(assemble(spec(), backlog(), skeleton()), tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "models.py").write_text("invoice = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app/models.py"], cwd=tmp_path, check=True)

    result = subprocess.run(
        [BASH, ".githooks/pre-commit"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runner_carries_the_circuit_breakers():
    bounded = spec(
        boundaries=LoopBoundaries(max_attempts_per_task=5, max_wall_clock_minutes=90)
    )
    runner = assemble(bounded, backlog(), skeleton()).file("runner/run_agent.py").contents

    assert "MAX_ATTEMPTS = 5" in runner
    assert "WALL_CLOCK_MINUTES = 90" in runner
    assert "BREAKER no-progress" in runner
    assert "BREAKER wall-clock" in runner
