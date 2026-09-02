"""The lint is the only quality gate in v1, so its behaviour is pinned here."""

from __future__ import annotations

import pytest

from ouroboros.inquisitor.lint import Severity, lint_spec
from ouroboros.models.spec import (
    Component,
    ProjectSpec,
    Requirement,
    StackProfile,
    VerificationPlan,
)


def clean_spec(**overrides) -> ProjectSpec:
    """A spec that passes the lint, so each test can break exactly one thing."""
    base = dict(
        name="Invoice Tracker",
        slug="invoice-tracker",
        one_line="Tracks freelance invoices and flags overdue ones.",
        problem="Freelancers lose money chasing invoices they forget to follow up on.",
        success_criteria=["A user can record an invoice and see it marked overdue after its due date."],
        non_goals=["No payment processing."],
        stack=StackProfile(
            language="Python",
            language_version="3.12",
            framework="FastAPI",
            package_manager="uv",
            corpus_covered=True,
        ),
        verification=VerificationPlan(
            install="uv sync",
            test="pytest -q",
            lint="ruff check .",
            smoke="uv run python -c 'import app'",
        ),
        components=[Component(name="api", responsibility="HTTP layer.", paths=["app/api/"])],
        requirements=[
            Requirement(
                id="R-001",
                statement="Record an invoice.",
                acceptance_criteria=["POST /invoices returns status 201 and an invoice id."],
            )
        ],
    )
    base.update(overrides)
    return ProjectSpec(**base)


def codes(spec: ProjectSpec) -> set[str]:
    return {f.code for f in lint_spec(spec).findings}


def test_clean_spec_passes():
    report = lint_spec(clean_spec())
    assert report.passed, [f.model_dump() for f in report.errors]


def test_open_questions_block_generation():
    report = lint_spec(clean_spec(open_questions=["Which auth provider?"]))
    assert not report.passed
    assert "OPEN_QUESTION" in {f.code for f in report.errors}


def test_placeholders_block_generation():
    assert "PLACEHOLDER" in codes(clean_spec(problem="Users need TBD."))


def test_requirement_without_acceptance_criteria_blocks():
    spec = clean_spec(
        requirements=[Requirement(id="R-001", statement="Record an invoice.")]
    )
    assert "NO_ACCEPTANCE_CRITERIA" in codes(spec)


def test_vague_criterion_blocks():
    spec = clean_spec(
        requirements=[
            Requirement(
                id="R-001",
                statement="Record an invoice.",
                acceptance_criteria=["The endpoint is fast and user-friendly."],
            )
        ]
    )
    assert "UNVERIFIABLE_CRITERION" in codes(spec)


def test_quantified_criterion_survives_vague_word():
    """'fast' is fine once it is pinned to a number — the lint blocks the unmeasurable."""
    spec = clean_spec(
        requirements=[
            Requirement(
                id="R-001",
                statement="Record an invoice.",
                acceptance_criteria=["POST /invoices responds in under 200 ms at p95."],
            )
        ]
    )
    assert "UNVERIFIABLE_CRITERION" not in codes(spec)


def test_dangling_dependency_blocks():
    spec = clean_spec(
        requirements=[
            Requirement(
                id="R-001",
                statement="Record an invoice.",
                acceptance_criteria=["POST /invoices returns status 201."],
                depends_on=["R-999"],
            )
        ]
    )
    assert "DANGLING_DEPENDENCY" in codes(spec)


def test_unresearched_stack_blocks():
    spec = clean_spec(
        stack=StackProfile(
            language="Elixir",
            language_version="1.17",
            package_manager="mix",
            corpus_covered=False,
        )
    )
    assert "STACK_NOT_RESEARCHED" in codes(spec)


def test_component_without_paths_blocks():
    spec = clean_spec(components=[Component(name="api", responsibility="HTTP layer.")])
    assert "COMPONENT_WITHOUT_PATHS" in codes(spec)


def test_missing_smoke_check_warns_but_does_not_block():
    spec = clean_spec(verification=VerificationPlan(install="uv sync", test="pytest -q"))
    report = lint_spec(spec)
    assert report.passed
    assert "NO_SMOKE_CHECK" in {f.code for f in report.warnings}


@pytest.mark.parametrize("field_name", ["success_criteria", "requirements", "components"])
def test_empty_core_sections_block(field_name):
    report = lint_spec(clean_spec(**{field_name: []}))
    assert not report.passed


def test_every_finding_carries_evidence_and_rectification():
    """A finding without a fix is an opinion, and opinions must not block generation."""
    report = lint_spec(clean_spec(open_questions=["?"], components=[]))
    assert report.findings
    for finding in report.findings:
        assert finding.evidence.strip()
        assert finding.rectification.strip()
        assert finding.severity in (Severity.ERROR, Severity.WARNING)
