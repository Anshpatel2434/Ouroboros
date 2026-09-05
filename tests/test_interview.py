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


def test_missing_fields_flags_blank_verification_commands():
    """'verification is not None' is not the same as 'verification is usable'."""
    draft = complete_draft()
    draft.verification = VerificationPlan(install="", test="", smoke="")

    missing = draft.missing_fields()
    assert any("verification commands" in field for field in missing)
    assert any("install" in field and "test" in field for field in missing)


def test_settled_summary_lists_defined_glossary_terms():
    """Terms already defined must be visible, or the interviewer re-asks them."""
    from ouroboros.inquisitor.graph import _settled_summary

    draft = complete_draft()
    draft.glossary = {"malformed URL": "Cannot be parsed into scheme and netloc."}

    assert "malformed URL" in _settled_summary(draft)


def test_integrator_receives_outstanding_lint_findings(deps):
    """Some findings can only be fixed by editing the spec, not by asking.

    A live interview looped four rounds asking yes/no questions while the lint
    repeated 'R-009 is redundant with R-006, remove it'. Only the integrator can
    apply that, so it has to see the findings.
    """
    from ouroboros.inquisitor.lint import LintFinding, LintReport, Severity

    llm = FakeLLM(
        {
            QuestionBatch: [batch("Anything else?")],
            SpecDraft: [complete_draft()],
            StackPlaybook: [playbook()],
            SemanticReport: [SemanticReport(findings=[])],
        }
    )
    state = {
        "draft": complete_draft(),
        "pending": batch("Anything else?"),
        "answers": [{"question_id": "q1", "value": "Yes."}],
        "transcript": [],
        "lint": LintReport(
            findings=[
                LintFinding(
                    code="COVERAGE_HOLE",
                    severity=Severity.ERROR,
                    location="requirements",
                    evidence="R-009 is redundant with R-006.",
                    rectification="Remove R-009 or clarify what it adds.",
                )
            ]
        ),
    }

    from ouroboros.inquisitor.graph import integrate

    integrate(state, deps(llm))

    prompt = [user for schema, user in llm.calls if schema is SpecDraft][0]
    assert "R-009 is redundant" in prompt
    assert "remove, merge, or restructure" in prompt


def test_integrator_prompt_stays_clean_when_the_lint_is_happy(deps):
    llm = FakeLLM(
        {SpecDraft: [complete_draft()], StackPlaybook: [playbook()]}
    )
    state = {
        "draft": complete_draft(),
        "pending": batch("Anything else?"),
        "answers": [{"question_id": "q1", "value": "Yes."}],
        "transcript": [],
        "lint": None,
    }

    from ouroboros.inquisitor.graph import integrate

    integrate(state, deps(llm))
    prompt = [user for schema, user in llm.calls if schema is SpecDraft][0]
    assert "refusing for these reasons" not in prompt


# --------------------------------------------------------------------------- #
# Draft merging — an omission must never be a deletion
# --------------------------------------------------------------------------- #

def test_merge_keeps_fields_the_model_omitted():
    """A live interview regressed to asking the project name again at round 5.

    The integrator returns the whole draft each round, so anything it forgets
    used to be deleted outright.
    """
    before = complete_draft()
    forgetful = SpecDraft(problem="A sharper problem statement.")

    after = before.merged_with(forgetful)

    assert after.problem == "A sharper problem statement.", "real edits must land"
    assert after.name == before.name
    assert after.one_line == before.one_line
    assert after.stack.language == "Python"
    assert after.verification.test == "pytest -q"
    assert after.components == before.components
    assert after.requirements == before.requirements
    assert after.success_criteria == before.success_criteria


def test_merge_still_allows_real_edits():
    """Removing a redundant requirement has to remain possible."""
    before = complete_draft()
    before.requirements = [
        Requirement(id="R-001", statement="Keep.", acceptance_criteria=["ok"]),
        Requirement(id="R-002", statement="Redundant.", acceptance_criteria=["ok"]),
    ]
    update = SpecDraft(
        requirements=[Requirement(id="R-001", statement="Keep.", acceptance_criteria=["ok"])]
    )

    after = before.merged_with(update)
    assert [r.id for r in after.requirements] == ["R-001"]


def test_merge_accumulates_glossary_terms():
    before = complete_draft()
    before.glossary = {"link": "A URL in a markdown file."}
    update = SpecDraft(glossary={"hit": "One matching line."})

    after = before.merged_with(update)
    assert set(after.glossary) == {"link", "hit"}


def test_merge_fills_blank_verification_commands_from_the_previous_draft():
    before = complete_draft()
    update = SpecDraft(verification=VerificationPlan(install="", test="uv run pytest"))

    after = before.merged_with(update)
    assert after.verification.install == "uv sync", "a blank must not erase a real command"
    assert after.verification.test == "uv run pytest"


def test_merge_preserves_researched_stack_coverage():
    """Gap research sets this; the model has no way to know it should stay true."""
    before = complete_draft()
    before.stack.corpus_covered = True
    update = SpecDraft(stack=StackProfile(
        language="Python", language_version="3.12", package_manager="uv"
    ))

    assert before.merged_with(update).stack.corpus_covered is True


def test_integrate_merges_instead_of_replacing(deps):
    llm = FakeLLM(
        {
            SpecDraft: [SpecDraft(problem="Only this field came back.")],
            StackPlaybook: [playbook()],
        }
    )
    state = {
        "draft": complete_draft(),
        "pending": batch("What is the problem?"),
        "answers": [{"question_id": "q1", "value": "Chasing invoices."}],
        "transcript": [],
        "lint": None,
    }

    from ouroboros.inquisitor.graph import integrate

    result = integrate(state, deps(llm))
    assert result["draft"].problem == "Only this field came back."
    assert result["draft"].name == "Invoice Tracker", "the rest must survive"


def test_flattened_requirements_are_repaired():
    """gpt-4o-mini intermittently flattens objects into alternating key/value items.

    Pydantic rejects it and the whole round dies, losing answers the developer
    already gave. The shape is unambiguous, so it is rebuilt.
    """
    draft = SpecDraft.model_validate(
        {
            "requirements": [
                "id", "R-001", "statement", "Count words.",
                "acceptance_criteria", ["Prints 10 lines."], "priority", "must",
                "id", "R-002", "statement", "Support --top.",
                "acceptance_criteria", ["Prints N lines."], "priority", "must",
            ]
        }
    )

    assert [r.id for r in draft.requirements] == ["R-001", "R-002"]
    assert draft.requirements[0].statement == "Count words."
    assert draft.requirements[1].acceptance_criteria == ["Prints N lines."]


def test_flattened_components_are_repaired():
    draft = SpecDraft.model_validate(
        {"components": ["name", "cli", "responsibility", "Parses args.", "paths", ["src/cli.py"]]}
    )
    assert draft.components[0].name == "cli"
    assert draft.components[0].paths == ["src/cli.py"]


def test_wellformed_lists_are_untouched():
    draft = SpecDraft.model_validate(
        {"requirements": [{"id": "R-001", "statement": "Do it.", "acceptance_criteria": ["ok"]}]}
    )
    assert draft.requirements[0].id == "R-001"


def test_unrecognised_shapes_are_left_for_pydantic_to_reject():
    """Repair must not paper over genuinely wrong data."""
    with pytest.raises(Exception):
        SpecDraft.model_validate({"requirements": ["totally", "unrelated", "strings"]})
