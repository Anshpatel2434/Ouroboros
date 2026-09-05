"""Generation: planning, assembly, self-review, and emission."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.generator.build import (
    GeneratorDeps,
    _classify_feedback,
    assemble,
    emit,
    generate,
)
from ouroboros.generator.planner import SkeletonPlan, _normalize_backlog, plan_backlog
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


# --------------------------------------------------------------------------- #
# Lessons from live runs
# --------------------------------------------------------------------------- #

def test_check_script_bodies_are_cleaned():
    """A live run produced literal backslash-n and a duplicate shebang.

    The template supplies the shebang and `set -euo pipefail`; a second one
    inside the body is a syntax error, so the check could never run.
    """
    messy = Backlog(
        tasks=[
            Task(
                id="T-001",
                title="Add search",
                intent="x",
                scope_paths=["app/"],
                check_script="#!/usr/bin/env bash\nset -euo pipefail\npytest -q tests/test_search.py",
            )
        ]
    )
    cleaned = _normalize_backlog(messy, spec()).tasks[0].check_script

    assert "\n" not in cleaned
    assert not cleaned.startswith("#!")
    assert "set -euo pipefail" not in cleaned
    assert cleaned == "pytest -q tests/test_search.py"


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
def test_cleaned_check_script_is_runnable(tmp_path):
    dirty = Backlog(
        tasks=[
            Task(
                id="T-001",
                title="Add search",
                requirement_id="R-001",
                intent="x",
                scope_paths=["app/"],
                done_when=["it works"],
                check_script="#!/usr/bin/env bash\nset -e\necho ran",
            )
        ]
    )
    emit(assemble(spec(), _normalize_backlog(dirty, spec()), skeleton()), tmp_path)
    result = subprocess.run(
        [BASH, "checks/T-001.sh"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ran" in result.stdout


def test_review_feedback_is_routed_to_whoever_can_act_on_it():
    """A live run turned harness-template findings into backlog tasks.

    Feedback about a malformed pre-commit hook went to the backlog planner,
    which produced a backlog of tasks to repair the harness instead of building
    the project. Findings must reach the planner that owns them, or nobody.
    """
    blueprint = assemble(spec(), backlog(), skeleton())
    review = ReviewReport(
        findings=[
            ReviewFinding(location="T-001", issue="weak check", evidence="e", fix="f", blocking=True),
            ReviewFinding(location="R-001", issue="not delivered", evidence="e", fix="f", blocking=True),
            ReviewFinding(location=".githooks/pre-commit", issue="malformed", evidence="e", fix="f", blocking=True),
            ReviewFinding(location="checks/T-001.sh", issue="bad shebang", evidence="e", fix="f", blocking=True),
            ReviewFinding(location="app/search.py", issue="wrong import", evidence="e", fix="f", blocking=True),
            ReviewFinding(location="T-001", issue="cosmetic", evidence="e", fix="f", blocking=False),
        ],
        verdict="rejected",
    )

    plan, skel, template = _classify_feedback(review, blueprint)

    assert "weak check" in plan and "not delivered" in plan
    assert "malformed" not in plan, "harness bugs must never become backlog tasks"
    assert "wrong import" in skel
    assert "malformed" not in skel
    assert len(template) == 2, "harness findings are reported, not fed back"
    assert "cosmetic" not in plan, "only blocking findings drive regeneration"


def test_template_findings_are_reported_as_our_bug_not_the_specs():
    rejection = ReviewReport(
        findings=[
            ReviewFinding(
                location=".githooks/pre-commit",
                issue="malformed",
                evidence="e",
                fix="f",
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
    assert any("bug in Ouroboros itself" in note for note in result.blueprint.notes)


def test_backlog_is_planned_in_chunks_for_a_large_spec():
    """One call for a whole backlog is fragile.

    A live run produced three tasks covering none of eight requirements, and a
    weaker model returned nothing valid at all. Requirements are planned a few
    at a time so each response stays small and none can be forgotten.
    """
    requirements = [
        Requirement(id=f"R-{n:03d}", statement=f"Do thing {n}.", acceptance_criteria=[f"Thing {n} happens."])
        for n in range(1, 8)
    ]
    big = spec(requirements=requirements)

    responses = [
        Backlog(
            tasks=[
                Task(
                    id=f"T-{n:03d}",
                    title=f"Implement thing {n}",
                    requirement_id=f"R-{n:03d}",
                    intent="x",
                    scope_paths=["app/"],
                    done_when=[f"Thing {n} happens."],
                    check_script="exit 0",
                )
                for n in group
            ]
        )
        for group in ([1, 2, 3], [4, 5, 6], [7])
    ]
    llm = FakeLLM({Backlog: responses})

    result = plan_backlog(llm, FileCorpusRetriever(), big)

    assert llm.count(Backlog) == 3, "seven requirements must not be one call"
    assert len(result.tasks) == 7
    assert {t.requirement_id for t in result.tasks} == {r.id for r in requirements}


def test_small_spec_is_planned_in_one_call():
    llm = FakeLLM({Backlog: [backlog()]})
    plan_backlog(llm, FileCorpusRetriever(), spec())
    assert llm.count(Backlog) == 1


def test_later_chunks_are_told_what_was_already_planned():
    """Cross-chunk dependencies are only expressible if later calls can see earlier ids."""
    requirements = [
        Requirement(id=f"R-{n:03d}", statement=f"Do thing {n}.", acceptance_criteria=["It happens."])
        for n in range(1, 8)
    ]
    responses = [
        Backlog(tasks=[Task(id=f"T-{n:03d}", title=f"Task {n}", requirement_id=f"R-{n:03d}", intent="x", scope_paths=["app/"])])
        for n in (1, 2, 3)
    ]
    llm = FakeLLM({Backlog: responses})
    plan_backlog(llm, FileCorpusRetriever(), spec(requirements=requirements))

    second_prompt = [u for s, u in llm.calls if s is Backlog][1]
    assert "already planned" in second_prompt
    assert "T-001" in second_prompt


def test_broken_python_manifest_is_caught_deterministically():
    """The exact manifest a live run produced, which the critic passed.

    Metadata under [tool], dependencies under [tool.poetry], in a uv project:
    valid TOML, plausible to read, and nothing installs from it. verify.sh could
    not have succeeded, so this must block.
    """
    broken = SkeletonPlan(
        files=[
            SkeletonFile(
                path="pyproject.toml",
                purpose="manifest",
                contents=(
                    '[tool]\nname = "noteseek"\nversion = "0.1.0"\n\n'
                    '[tool.poetry.dependencies]\npython = "^3.12"\nclick = "^8.0"\n'
                ),
            )
        ]
    )
    findings = structural_findings(assemble(spec(), backlog(), broken))
    issues = {f.issue for f in findings if f.blocking}

    assert "pyproject.toml has no [project] table." in issues
    assert any("Poetry" in issue for issue in issues)


def test_valid_python_manifest_passes():
    good = SkeletonPlan(
        files=[
            SkeletonFile(
                path="pyproject.toml",
                purpose="manifest",
                contents=(
                    '[project]\nname = "noteseek"\nversion = "0.1.0"\n'
                    'dependencies = ["click"]\n\n'
                    '[project.scripts]\nnoteseek = "noteseek.cli:main"\n'
                ),
            )
        ]
    )
    findings = [f for f in structural_findings(assemble(spec(), backlog(), good)) if f.blocking]
    assert not [f for f in findings if "pyproject" in f.location]


def test_unparseable_manifest_is_caught():
    for path, contents in [
        ("pyproject.toml", "[project\nname = broken"),
        ("package.json", '{"name": "x",}'),
    ]:
        plan = SkeletonPlan(files=[SkeletonFile(path=path, purpose="manifest", contents=contents)])
        findings = structural_findings(assemble(spec(), backlog(), plan))
        assert any(f.blocking and path in f.location for f in findings), path


def test_pep621_dependency_table_is_caught():
    """[project] existing is not enough; its shape has to be installable.

    A live run declared dependencies as a table of Poetry-style constraints and
    listed sqlite3 — a stdlib module with no distribution to install.
    """
    plan = SkeletonPlan(
        files=[
            SkeletonFile(
                path="pyproject.toml",
                purpose="manifest",
                contents=(
                    '[project]\nname = "noteseek"\nversion = "0.1.0"\n'
                    'authors = ["Someone <a@b.c>"]\n\n'
                    '[project.dependencies]\nclick = "^8.0"\nsqlite3 = "^3.36"\n'
                ),
            )
        ]
    )
    issues = {f.issue for f in structural_findings(assemble(spec(), backlog(), plan)) if f.blocking}

    assert "project.dependencies is not an array." in issues
    assert "project.authors has the wrong shape." in issues


def test_stdlib_dependency_is_caught():
    plan = SkeletonPlan(
        files=[
            SkeletonFile(
                path="pyproject.toml",
                purpose="manifest",
                contents=(
                    '[project]\nname = "noteseek"\nversion = "0.1.0"\n'
                    'dependencies = ["click>=8.0", "sqlite3>=3.36"]\n'
                ),
            )
        ]
    )
    issues = {f.issue for f in structural_findings(assemble(spec(), backlog(), plan)) if f.blocking}
    assert any("standard library" in issue for issue in issues)


def test_wellformed_pep621_manifest_passes():
    plan = SkeletonPlan(
        files=[
            SkeletonFile(
                path="pyproject.toml",
                purpose="manifest",
                contents=(
                    '[project]\nname = "noteseek"\nversion = "0.1.0"\n'
                    'requires-python = ">=3.12"\n'
                    'dependencies = ["click>=8.0"]\n'
                    'authors = [{name = "A", email = "a@example.com"}]\n\n'
                    '[project.scripts]\nnoteseek = "noteseek.cli:main"\n'
                ),
            )
        ]
    )
    findings = [f for f in structural_findings(assemble(spec(), backlog(), plan)) if f.blocking]
    assert not [f for f in findings if "pyproject" in f.location]


def _skeleton_with(manifest: str, module: str) -> SkeletonPlan:
    return SkeletonPlan(
        files=[
            SkeletonFile(path="pyproject.toml", purpose="manifest", contents=manifest),
            SkeletonFile(path="src/app/cli.py", purpose="cli", contents=module),
        ]
    )


def test_undeclared_third_party_import_is_caught():
    """The manifest and the code come from separate calls, so they drift.

    A live run produced a cli.py importing click next to `dependencies = []`.
    Each file is fine alone; together nothing installs and the smoke command
    dies on ImportError.
    """
    plan = _skeleton_with(
        '[project]\nname = "invoice-tracker"\nversion = "0.1.0"\ndependencies = []\n',
        "import click\n\ndef main():\n    click.echo('hi')\n",
    )
    findings = [f for f in structural_findings(assemble(spec(), backlog(), plan)) if f.blocking]
    assert any("imports 'click'" in f.issue for f in findings)


def test_declared_import_passes():
    plan = _skeleton_with(
        '[project]\nname = "invoice-tracker"\nversion = "0.1.0"\n'
        'dependencies = ["click>=8.0"]\n',
        "import click\n\ndef main():\n    click.echo('hi')\n",
    )
    findings = [f for f in structural_findings(assemble(spec(), backlog(), plan)) if f.blocking]
    assert not any("click" in f.issue for f in findings)


def test_dev_group_dependency_counts_as_declared():
    plan = _skeleton_with(
        '[project]\nname = "invoice-tracker"\nversion = "0.1.0"\ndependencies = []\n\n'
        '[dependency-groups]\ndev = ["pytest>=8.0"]\n',
        "import pytest\n",
    )
    findings = [f for f in structural_findings(assemble(spec(), backlog(), plan)) if f.blocking]
    assert not any("pytest" in f.issue for f in findings)


def test_stdlib_and_own_package_imports_are_not_flagged():
    plan = _skeleton_with(
        '[project]\nname = "invoice-tracker"\nversion = "0.1.0"\ndependencies = []\n',
        "import sqlite3\nimport json\nfrom invoice_tracker import cli\n",
    )
    findings = [f for f in structural_findings(assemble(spec(), backlog(), plan)) if f.blocking]
    assert not [f for f in findings if "imports" in f.issue]
