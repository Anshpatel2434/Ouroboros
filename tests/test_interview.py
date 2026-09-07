"""The interview loop: ask, integrate, research, lint, converge or stop."""

from __future__ import annotations

import pytest

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.inquisitor.graph import InquisitorDeps, InterviewSession
from ouroboros.inquisitor.research import StackPlaybook, stack_slug
from ouroboros.inquisitor.semantic import SemanticReport
from ouroboros.models.interview import Question, QuestionBatch, SpecDraft
from ouroboros.models.spec import Component, Requirement, StackProfile, VerificationPlan
from tests.fakes import FakeLLM, patch_responses


def batch(*texts: str, group=None) -> QuestionBatch:
    from ouroboros.models.patches import FieldGroup

    return QuestionBatch(
        questions=[
            Question(
                id=f"q{i}",
                header="Scope",
                text=text,
                why_it_matters="Fills a required spec field.",
                field_group=group or FieldGroup.REQUIREMENTS,
            )
            for i, text in enumerate(texts, start=1)
        ],
        rationale="Narrowing the spec.",
    )


def group_batch(*groups) -> QuestionBatch:
    """One question per field group, so a round can fill several parts."""
    return QuestionBatch(
        questions=[
            Question(
                id=f"q{i}",
                header=g.value,
                text=f"Tell me about {g.value}.",
                why_it_matters=f"Fills the {g.value} part of the spec.",
                field_group=g,
            )
            for i, g in enumerate(groups, start=1)
        ],
        rationale="Filling the spec group by group.",
    )


def answers_for(state) -> list[dict]:
    return [{"question_id": q["id"], "value": "As described."} for q in state["questions"]]


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


def full_llm(draft=None, **_ignored):
    """A model scripted for the patch architecture.

    Only the wording of a question is scripted. Which part of the spec it is
    about is decided by the system, so there is nothing here to get wrong.
    """
    from ouroboros.models.interview import SingleQuestion

    target = draft or complete_draft()
    responses = dict(patch_responses(target))
    responses[SingleQuestion] = [
        SingleQuestion(
            header="Scope",
            text="Tell me more about this part.",
            why_it_matters="Fills a required part of the spec.",
        )
    ]
    responses[StackPlaybook] = [playbook()]
    responses[SemanticReport] = [SemanticReport(findings=[])]
    return FakeLLM(responses)


def run_until_settled(session, brief="An invoice tracker.", limit=8):
    state = session.start(brief)
    for _ in range(limit):
        if state["status"] != "interviewing" or not state["questions"]:
            break
        state = session.answer(answers_for(state))
    return state


def test_interview_converges_to_a_clean_spec(deps):
    session = InterviewSession("t1", deps=deps(full_llm()))
    state = run_until_settled(session)

    assert state["status"] == "ready", state.get("lint")
    assert state["spec"]["name"] == "Invoice Tracker"
    assert state["questions"] == []


def test_an_answer_only_touches_its_own_field_group():
    """The architectural guarantee, at the level it actually lives.

    The old integrator rewrote the whole draft each round, so a forgotten field
    was a deleted field. Extraction is confined to one group, which makes losing
    an unrelated field unrepresentable rather than merely unlikely.
    """
    from ouroboros.inquisitor.extract import apply_patch
    from ouroboros.models.patches import FieldGroup, RequirementsPatch

    before = complete_draft()
    after = apply_patch(
        before,
        FieldGroup.REQUIREMENTS,
        RequirementsPatch(
            requirements=[
                Requirement(id="R-042", statement="Only this lands.", acceptance_criteria=["ok"])
            ]
        ),
    )

    assert [r.id for r in after.requirements] == ["R-042"]
    assert after.name == before.name
    assert after.stack.language == before.stack.language
    assert after.verification.test == before.verification.test
    assert after.components == before.components


def test_the_agenda_is_derived_from_the_draft_not_the_model():
    """Which part of the spec to ask about is a fact, not a judgement call."""
    from ouroboros.inquisitor.agenda import plan_round
    from ouroboros.models.patches import FieldGroup

    empty = SpecDraft()
    groups = [group for group, _ in plan_round(empty, [])]

    assert FieldGroup.IDENTITY in groups
    assert len(groups) <= 3, "a round stays answerable"

    filled = complete_draft()
    assert plan_round(filled, []) == [], "nothing missing means nothing to ask"


def test_incomplete_draft_triggers_another_round(deps):
    from ouroboros.models.patches import FieldGroup

    partial = SpecDraft(name="Half a spec", one_line="Not finished.", problem="Unclear.")
    llm = full_llm(partial, batches=[group_batch(FieldGroup.IDENTITY)])
    session = InterviewSession("t2", deps=deps(llm))
    session.start("Something vague.")
    result = session.answer([{"question_id": "q1", "value": "Not sure yet."}])

    assert result["status"] == "interviewing"
    assert result["questions"], "an incomplete draft must produce more questions"
    assert "stack" in result["missing_fields"]


def test_round_cap_stops_the_interview(deps):
    """An interviewer that cannot converge must stop, not question forever."""
    from ouroboros.models.patches import FieldGroup

    llm = full_llm(SpecDraft(name="Never finished"), batches=[group_batch(FieldGroup.IDENTITY)])
    session = InterviewSession("t3", deps=deps(llm))
    state = run_until_settled(session, "A vague idea.")

    assert state["status"] == "exhausted"
    assert state["spec"] is None, "generation must stay refused"


def test_unknown_stack_is_researched_and_written_back(deps, tmp_path):
    """Gap research compounds the corpus instead of guessing (D7/D9)."""
    from ouroboros.models.patches import FieldGroup

    llm = full_llm(batches=[group_batch(FieldGroup.STACK)])
    session = InterviewSession("t4", deps=deps(llm))
    state = session.start("An invoice tracker.")
    result = session.answer(answers_for(state))

    slug = stack_slug(
        StackProfile(
            language="Python", language_version="3.12", framework="FastAPI", package_manager="uv"
        )
    )
    written = tmp_path / "06-stack-playbooks" / f"{slug}.md"
    assert written.exists(), "the researched stack must be added to the corpus"
    assert "uv sync" in written.read_text(encoding="utf-8")
    assert any("Researched" in n for n in result["notices"])


def test_transcript_records_every_exchange(deps):
    from ouroboros.models.patches import FieldGroup

    llm = full_llm(batches=[group_batch(FieldGroup.IDENTITY)])
    session = InterviewSession("t5", deps=deps(llm))
    state = session.start("An invoice tracker.")
    result = session.answer([{"question_id": "q1", "value": "Chasing invoices."}])

    assert result["transcript"] == [
        {"question": "Tell me more about this part.", "answer": "Chasing invoices."}
    ]


def test_glossary_is_swept_even_when_no_question_targets_it(deps):
    """Definitions arrive inside answers about other things.

    Terms were once answered twice and stored zero times, so the lint kept
    calling them undefined and the interviewer kept re-asking.
    """
    from ouroboros.models.patches import FieldGroup, GlossaryPatch

    target = complete_draft()
    target.glossary = {"overdue": "Past its due date and unpaid."}
    llm = full_llm(target, batches=[group_batch(FieldGroup.REQUIREMENTS)])

    session = InterviewSession("t-gloss", deps=deps(llm))
    state = session.start("An invoice tracker.")
    result = session.answer(answers_for(state))

    assert llm.count(GlossaryPatch) == 1, "the glossary must be swept every round"
    assert "overdue" in result["draft"]["glossary"]


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


def test_junk_verification_commands_are_filled_from_the_playbook(deps, tmp_path):
    """Once a stack is researched its real commands are a fact we hold.

    An interview settled on install='install', could only repair it by asking
    again, waived it, and generated a verify.sh whose first step ran a word.
    """
    from ouroboros.inquisitor.graph import ensure_stack_coverage
    from ouroboros.models.spec import VerificationPlan

    llm = full_llm()
    draft = complete_draft()
    draft.stack.corpus_covered = False
    draft.verification = VerificationPlan(install="install", test="test")

    result = ensure_stack_coverage({"draft": draft, "notices": []}, deps(llm))
    verification = result["draft"].verification

    assert verification.install == "uv sync"
    assert verification.test == "pytest -q"
    assert any("Filled verification commands" in n for n in result["notices"])


def test_a_real_command_is_never_overwritten(deps, tmp_path):
    from ouroboros.inquisitor.graph import ensure_stack_coverage
    from ouroboros.models.spec import VerificationPlan

    llm = full_llm()
    draft = complete_draft()
    draft.stack.corpus_covered = False
    draft.verification = VerificationPlan(install="poetry install", test="test")

    result = ensure_stack_coverage({"draft": draft, "notices": []}, deps(llm))
    assert result["draft"].verification.install == "poetry install"
    assert result["draft"].verification.test == "pytest -q"
