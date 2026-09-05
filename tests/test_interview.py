"""The interview loop: ask, integrate, research, lint, converge or stop."""

from __future__ import annotations

import pytest

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.inquisitor.graph import InquisitorDeps, InterviewSession
from ouroboros.inquisitor.research import StackPlaybook, stack_slug
from ouroboros.inquisitor.semantic import SemanticReport
from ouroboros.models.interview import Question, QuestionBatch, SpecDraft
from ouroboros.models.spec import Component, Requirement, StackProfile, VerificationPlan
from tests.fakes import FakeLLM


def batch(*texts: str) -> QuestionBatch:
    return QuestionBatch(
        questions=[
            Question(
                id=f"q{i}",
                header="Scope",
                text=text,
                why_it_matters="Fills a required spec field.",
            )
            for i, text in enumerate(texts, start=1)
        ],
        rationale="Narrowing the spec.",
    )


def complete_draft() -> SpecDraft:
    return SpecDraft(
        name="Invoice Tracker",
        slug="invoice-tracker",
        one_line="Tracks freelance invoices and flags overdue ones.",
        problem="Freelancers lose money chasing invoices they forget about.",
        success_criteria=["An invoice past its due date shows as overdue."],
        non_goals=["No payment processing."],
        stack=StackProfile(
            language="Python",
            language_version="3.12",
            framework="FastAPI",
            package_manager="uv",
        ),
        verification=VerificationPlan(install="uv sync", test="pytest -q", smoke="uv run python -c 'import app'"),
        components=[Component(name="api", responsibility="HTTP layer.", paths=["app/api/"])],
        requirements=[
            Requirement(
                id="R-001",
                statement="Record an invoice.",
                acceptance_criteria=["POST /invoices returns status 201."],
            )
        ],
    )


def playbook() -> StackPlaybook:
    return StackPlaybook(
        language="Python",
        language_version="3.12",
        framework="FastAPI",
        package_manager="uv",
        install="uv sync",
        test="pytest -q",
        lint="ruff check .",
        smoke="uv run python -c 'import app'",
        layout_notes=["Application package under app/."],
        gotchas=["uv sync needs a committed lockfile in CI."],
    )


@pytest.fixture
def deps(tmp_path):
    """Interview deps whose corpus write-back is redirected away from the real corpus."""

    def make(llm) -> InquisitorDeps:
        return InquisitorDeps(
            llm=llm,
            retriever=FileCorpusRetriever(),
            max_rounds=4,
            corpus_root=tmp_path,
        )

    return make


def test_interview_converges_to_a_clean_spec(deps):
    llm = FakeLLM(
        {
            QuestionBatch: [batch("What problem does this solve?", "Which stack?")],
            SpecDraft: [complete_draft()],
            StackPlaybook: [playbook()],
            SemanticReport: [SemanticReport(findings=[])],
        }
    )
    session = InterviewSession("t1", deps=deps(llm))

    opened = session.start("A tool for tracking freelance invoices.")
    assert opened["status"] == "interviewing"
    assert len(opened["questions"]) == 2

    result = session.answer(
        [{"question_id": "q1", "value": "Chasing invoices."}, {"question_id": "q2", "value": "Python."}]
    )

    assert result["status"] == "ready"
    assert result["spec"]["name"] == "Invoice Tracker"
    assert result["lint"] is not None
    assert result["questions"] == []


def test_incomplete_draft_triggers_another_round(deps):
    llm = FakeLLM(
        {
            QuestionBatch: [batch("What problem does this solve?")],
            SpecDraft: [SpecDraft(name="Half a spec", one_line="Not finished.")],
            SemanticReport: [SemanticReport(findings=[])],
        }
    )
    session = InterviewSession("t2", deps=deps(llm))
    session.start("Something vague.")
    result = session.answer([{"question_id": "q1", "value": "Not sure yet."}])

    assert result["status"] == "interviewing"
    assert result["round"] == 2
    assert result["questions"], "an incomplete draft must produce more questions"
    assert "stack" in result["missing_fields"]


def test_round_cap_stops_the_interview(deps):
    """An interviewer that cannot converge must stop, not question forever."""
    llm = FakeLLM(
        {
            QuestionBatch: [batch("Still unclear?")],
            SpecDraft: [SpecDraft(name="Never finished")],
            SemanticReport: [SemanticReport(findings=[])],
        }
    )
    session = InterviewSession("t3", deps=deps(llm))
    session.start("A vague idea.")

    for _ in range(4):
        state = session.answer([{"question_id": "q1", "value": "Still unsure."}])
        if state["status"] != "interviewing":
            break

    assert state["status"] == "exhausted"
    assert state["spec"] is None, "generation must stay refused"
    assert any("Stopped after" in n for n in state["notices"])


def test_unknown_stack_is_researched_and_written_back(deps, tmp_path):
    """Gap research compounds the corpus instead of guessing (D7/D9)."""
    llm = FakeLLM(
        {
            QuestionBatch: [batch("Which stack?")],
            SpecDraft: [complete_draft()],
            StackPlaybook: [playbook()],
            SemanticReport: [SemanticReport(findings=[])],
        }
    )
    session = InterviewSession("t4", deps=deps(llm))
    session.start("An invoice tracker.")
    result = session.answer([{"question_id": "q1", "value": "Python and FastAPI."}])

    slug = stack_slug(
        StackProfile(
            language="Python", language_version="3.12", framework="FastAPI", package_manager="uv"
        )
    )
    written = tmp_path / "06-stack-playbooks" / f"{slug}.md"
    assert written.exists(), "the researched stack must be added to the corpus"

    text = written.read_text(encoding="utf-8")
    assert "## Key knowledge" in text and "uv sync" in text
    assert result["spec"]["stack"]["corpus_covered"] is True
    assert any("Researched" in n for n in result["notices"])


def test_transcript_records_every_exchange(deps):
    llm = FakeLLM(
        {
            QuestionBatch: [batch("What problem does this solve?")],
            SpecDraft: [complete_draft()],
            StackPlaybook: [playbook()],
            SemanticReport: [SemanticReport(findings=[])],
        }
    )
    session = InterviewSession("t5", deps=deps(llm))
    session.start("An invoice tracker.")
    result = session.answer([{"question_id": "q1", "value": "Chasing invoices."}])

    assert result["transcript"] == [
        {"question": "What problem does this solve?", "answer": "Chasing invoices."}
    ]


def test_missing_fields_names_unfenced_components():
    """The agenda must surface anything the lint will refuse for.

    A live interview stalled here: every required field was filled, so the
    interviewer was told there was nothing left to ask, while the lint kept
    refusing because no component had paths.
    """
    draft = complete_draft()
    draft.components = [Component(name="Indexer", responsibility="Builds the index.", paths=[])]

    missing = draft.missing_fields()
    assert any("paths for components" in field and "Indexer" in field for field in missing)


def test_missing_fields_names_requirements_without_criteria():
    draft = complete_draft()
    draft.requirements = [Requirement(id="R-009", statement="Search notes.")]

    missing = draft.missing_fields()
    assert any("acceptance criteria" in field and "R-009" in field for field in missing)


def test_complete_draft_reports_nothing_missing():
    assert complete_draft().missing_fields() == []
