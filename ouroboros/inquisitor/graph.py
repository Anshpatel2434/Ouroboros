"""The interview graph.

A loop: ask two or three questions, fold the answers into the working draft,
research the stack if we have never seen it, lint, and either finish or ask the
next round targeted at exactly what the lint refused.

The loop has a hard round cap for the same reason the generated runner has
circuit breakers: an interviewer that cannot converge must stop and say so
rather than question someone forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.inquisitor.findings import FindingLedger, FindingRecord, Resolution
from ouroboros.inquisitor.agenda import plan_round
from ouroboros.inquisitor.extract import GROUP_BRIEF, extract_group
from ouroboros.inquisitor.lint import LintReport, lint_spec
from ouroboros.inquisitor.prompts import INTERVIEWER
from ouroboros.inquisitor.research import (
    ensure_playbook,
    find_playbook,
    playbook_commands,
)
from ouroboros.inquisitor.semantic import full_lint
from ouroboros.llm.client import LLM, default_llm
from ouroboros.models.patches import FieldGroup
from ouroboros.models.interview import (
    InterviewTurn,
    infer_kind,
    options_from_prose,
    Question,
    QuestionBatch,
    SingleQuestion,
    SpecDraft,
)
from ouroboros.models.spec import ProjectSpec, VerificationPlan

Status = Literal["interviewing", "ready", "exhausted"]

MAX_ROUNDS = 12


class InterviewState(TypedDict, total=False):
    brief: str
    ledger: FindingLedger
    draft: SpecDraft
    round: int
    pending: QuestionBatch | None
    answers: list[dict[str, str]]
    transcript: list[InterviewTurn]
    lint: LintReport | None
    spec: ProjectSpec | None
    status: Status
    notices: list[str]


@dataclass
class InquisitorDeps:
    llm: LLM = field(default_factory=default_llm)
    retriever: FileCorpusRetriever = field(default_factory=FileCorpusRetriever)
    max_rounds: int = MAX_ROUNDS
    corpus_root: Path | None = None


def _corpus_context(deps: InquisitorDeps, query: str, limit: int = 4) -> str:
    """Ground questions in what we actually know, so they land on real mechanics."""
    hits = deps.retriever.search(query, limit=limit)
    if not hits:
        return "No corpus guidance retrieved for this brief."
    return "\n".join(f"- {h.document.title}: {h.document.relevance}" for h in hits)


def _settled_summary(draft: SpecDraft) -> str:
    """Compact list of what the interview has already established."""
    lines: list[str] = []
    for field in ("name", "slug", "one_line", "problem"):
        value = getattr(draft, field, None)
        if value:
            lines.append(f"- {field}: {value}")
    if draft.stack:
        lines.append(
            f"- stack: {draft.stack.language} {draft.stack.language_version}, "
            f"framework={draft.stack.framework or 'none'}, "
            f"package_manager={draft.stack.package_manager}, "
            f"database={draft.stack.database or 'none'}"
        )
    if draft.verification:
        commands = ", ".join(f"{k}={v}" for k, v in draft.verification.commands())
        lines.append(f"- verification: {commands}")
    if draft.success_criteria:
        lines.append(f"- success_criteria: {len(draft.success_criteria)} recorded")
    if draft.non_goals:
        lines.append(f"- non_goals: {len(draft.non_goals)} recorded")
    if draft.components:
        lines.append(
            "- components: " + ", ".join(c.name for c in draft.components)
        )
    if draft.requirements:
        lines.append(
            "- requirements: "
            + ", ".join(f"{r.id} ({r.statement[:60]})" for r in draft.requirements)
        )
    if draft.glossary:
        lines.append("- glossary defines: " + ", ".join(sorted(draft.glossary)))
    return "\n".join(lines)


def _findings_text(report: LintReport | None) -> str:
    if report is None:
        return ""
    return "\n".join(
        f"- [{f.code}] {f.location}: {f.evidence} -> {f.rectification}"
        for f in report.errors
    )



def _ask_round(
    state: InterviewState,
    deps: InquisitorDeps,
    draft: SpecDraft,
    to_ask: list[FindingRecord],
) -> QuestionBatch:
    """One question per field group the system decided needs attention.

    Each call is tiny and single-purpose, and the group is attached by us
    afterwards rather than chosen by the model, so an answer always lands in the
    part of the spec its question was about. An earlier version asked the model
    to tag its own questions; gpt-4o-mini omitted the tag, every answer fell
    through to one default group, and ten rounds of good answers landed nowhere.
    """
    planned = plan_round(draft, to_ask)
    if not planned:
        return QuestionBatch(questions=[], rationale="")

    settled = _settled_summary(draft)
    asked = [t.question.text for t in state.get("transcript", [])][-8:]
    questions: list[Question] = []

    for index, (group, reason) in enumerate(planned, start=1):
        sections = [f"Project brief:\n{state.get('brief', '')}"]
        if settled:
            sections.append(
                "Already settled — never ask about any of these again:\n" + settled
            )
        if asked:
            sections.append(
                "Questions already asked; do not repeat them:\n"
                + "\n".join(f"- {q}" for q in asked)
            )
        sections.append(
            f"Ask exactly one question about the {group.value} part of the "
            f"specification.\nWhat that part covers: {GROUP_BRIEF[group]}\n"
            f"Why it is on the agenda: {reason}"
        )
        sections.append(
            "Offer concrete options when the sane answers are few. Ask one "
            "question only; another will follow if more is needed."
        )

        single = deps.llm.structured(
            SingleQuestion,
            system=INTERVIEWER,
            user="\n\n".join(sections),
            role="questions",
        )
        text, parsed = options_from_prose(single.text) if not single.options else (single.text, [])
        options = single.options or parsed
        questions.append(
            Question(
                id=f"q{index}",
                header=single.header,
                text=text,
                kind=infer_kind(text, options, single.kind, group),
                options=options,
                why_it_matters=single.why_it_matters,
                field_group=group,
            )
        )

    return QuestionBatch(
        questions=questions,
        rationale="Filling the parts of the spec that are still open.",
    )


def open_interview(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    draft = state.get("draft") or SpecDraft()
    batch = _ask_round(state, deps, draft, [])
    return {
        "draft": draft,
        "pending": batch,
        "round": 1,
        "transcript": state.get("transcript", []),
        "status": "interviewing",
        "notices": state.get("notices", []),
    }


def collect_answers(state: InterviewState) -> dict[str, Any]:
    """Hand the questions to the UI and wait. Resumed with Command(resume=...)."""
    pending = state.get("pending")
    answers = interrupt(
        {
            "round": state.get("round", 1),
            "questions": [q.model_dump() for q in (pending.questions if pending else [])],
            "rationale": pending.rationale if pending else "",
        }
    )
    return {"answers": _normalize_answers(answers)}


def _normalize_answers(answers: Any) -> list[dict[str, str]]:
    """Accept either a list of {question_id, value} or a plain id->value mapping."""
    if isinstance(answers, dict):
        return [{"question_id": k, "value": str(v)} for k, v in answers.items()]
    normalized = []
    for item in answers or []:
        if isinstance(item, dict):
            normalized.append(
                {
                    "question_id": str(item.get("question_id", "")),
                    "value": str(item.get("value", "")),
                }
            )
    return normalized


def integrate(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    """Extract each answer into the one field group it belongs to.

    Never a whole-draft rewrite. Each question declares its field group, the
    answer is extracted into that group with a small schema, and every other
    part of the draft is untouchable for the duration. Losing an unrelated field
    is not merely unlikely here, it is unrepresentable.
    """
    draft = state.get("draft") or SpecDraft()
    pending = state.get("pending")
    by_id = {q.id: q for q in (pending.questions if pending else [])}

    turns = list(state.get("transcript", []))
    by_group: dict[FieldGroup, list[str]] = {}
    exchange_lines: list[str] = []

    for answer in state.get("answers", []):
        question = by_id.get(answer["question_id"])
        if question is None:
            continue
        turns.append(InterviewTurn(question=question, answer=answer["value"]))
        line = f"Q: {question.text}\nA: {answer['value']}"
        exchange_lines.append(line)
        by_group.setdefault(question.field_group, []).append(line)

    if not exchange_lines:
        return {"transcript": turns, "answers": []}

    everything = "\n\n".join(exchange_lines)
    for group, lines in by_group.items():
        draft = extract_group(deps.llm, draft, group, "\n\n".join(lines))

    # Definitions arrive inside answers about other things, so the glossary is
    # always swept. It used to be filled only when a question happened to target
    # it, which is why terms answered twice were stored zero times.
    if FieldGroup.GLOSSARY not in by_group:
        draft = extract_group(deps.llm, draft, FieldGroup.GLOSSARY, everything)

    return {"draft": draft, "transcript": turns, "answers": []}


def ensure_stack_coverage(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    """Research an unknown stack once, write it back, and unblock the lint."""
    draft = state.get("draft") or SpecDraft()
    notices = list(state.get("notices", []))

    if draft.stack is None:
        return {"notices": notices}

    if not draft.stack.corpus_covered:
        playbook, researched = ensure_playbook(
            deps.llm, deps.retriever, draft.stack, root=deps.corpus_root
        )
        draft.stack.corpus_covered = True
        if researched and playbook is not None:
            notices.append(
                f"Researched {draft.stack.language} "
                f"{draft.stack.framework or ''}".strip() + " and added it to the corpus."
            )
            if draft.verification is None:
                draft.verification = playbook.to_verification()

    draft = _adopt_known_commands(draft, deps, notices)
    return {"draft": draft, "notices": notices}


def _adopt_known_commands(
    draft: SpecDraft, deps: InquisitorDeps, notices: list[str]
) -> SpecDraft:
    """Fill blank or nonsense verification commands from the researched playbook.

    Once a stack has been researched, its real commands are a fact we hold. An
    interview once settled on `install` set to the word "install" and, because
    the only repair route was to ask again, waived it and generated a verify.sh
    whose first step ran a word. Correcting from the corpus is both more
    reliable than re-asking and free.
    """
    from ouroboros.inquisitor.lint import LABEL_WORDS

    document = find_playbook(deps.retriever, draft.stack)
    if document is None:
        return draft

    known = playbook_commands(document)
    if not known:
        return draft

    if draft.verification is None:
        draft.verification = VerificationPlan(
            install=known.get("install", ""), test=known.get("test", "")
        )

    adopted: list[str] = []
    for label in ("install", "test", "lint", "typecheck", "build", "smoke"):
        current = (getattr(draft.verification, label) or "").strip()
        if current and current.lower() not in LABEL_WORDS:
            continue  # The developer gave a real command; it stands.
        replacement = known.get(label)
        if replacement:
            setattr(draft.verification, label, replacement)
            adopted.append(f"{label}={replacement}")

    if adopted:
        notices.append(
            "Filled verification commands from the researched stack playbook: "
            + ", ".join(adopted)
        )
    return draft


def _ledger_of(state: InterviewState) -> FindingLedger:
    """The checkpointer round-trips state through msgpack, so this may be a dict."""
    raw = state.get("ledger")
    if isinstance(raw, FindingLedger):
        return raw
    if isinstance(raw, dict):
        return FindingLedger.model_validate(raw)
    return FindingLedger()


def _is_ready(draft: SpecDraft, spec, report: LintReport | None) -> bool:
    """A clean lint is necessary but not sufficient.

    The deterministic lint can only judge the parts of a spec that exist; it has
    nothing to say about a spec with one requirement for an entire e-commerce
    site. The agenda knows, so readiness requires it to be empty too.
    """
    if spec is None or report is None or not report.passed:
        return False
    return not draft.missing_fields()


def _evaluate(draft: SpecDraft, deps: InquisitorDeps) -> tuple[ProjectSpec | None, LintReport | None]:
    """Lint the draft, paying for the LLM judge only when it can say something.

    Deterministic checks run first and are free. The semantic pass is gated
    behind them: asking a judge to reason about a spec that is still missing its
    verification commands produces findings about the wrong thing, and each new
    finding it invents is another round nobody needed.
    """
    spec = draft.to_spec()
    if spec is None:
        return None, None

    report = lint_spec(spec)
    if report.passed and not draft.missing_fields():
        report = full_lint(deps.llm, spec)
    return spec, report


def _resolve_findings(
    draft: SpecDraft, ledger: FindingLedger, report: LintReport | None, deps: InquisitorDeps
) -> tuple[SpecDraft, list[FindingRecord], bool]:
    """Push every live finding one rung up the ladder.

    Returns the draft after any edits, the findings that need the developer, and
    whether anything was edited.
    """
    live = ledger.observe(report)
    to_ask: list[FindingRecord] = []
    edited = False

    for record in live:
        if ledger.attempt(record) is Resolution.EDIT:
            draft = extract_group(
                deps.llm,
                draft,
                record.group,
                exchange="(no new answers — this is a correction pass)",
                guidance=record.as_instruction(),
            )
            edited = True
        else:
            to_ask.append(record)

    return draft, to_ask, edited


def assess(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    draft = state.get("draft") or SpecDraft()
    round_no = state.get("round", 1)
    ledger = _ledger_of(state)

    spec, report = _evaluate(draft, deps)
    if _is_ready(draft, spec, report):
        return {
            "lint": report,
            "spec": spec,
            "ledger": ledger,
            "status": "ready",
            "pending": None,
            "notices": _notices_with_waivers(state, ledger),
        }

    draft, to_ask, edited = _resolve_findings(draft, ledger, report, deps)

    # Corrections were applied, so re-check before spending a question on
    # something already fixed. One re-check per round bounds the cost.
    if edited:
        spec, report = _evaluate(draft, deps)
        if _is_ready(draft, spec, report):
            return {
                "draft": draft,
                "lint": report,
                "spec": spec,
                "ledger": ledger,
                "status": "ready",
                "pending": None,
                "notices": _notices_with_waivers(state, ledger),
            }
        to_ask = [r for r in ledger.observe(report) if r.next_resolution() is Resolution.ASK]

    # Anything that has used up its attempts becomes a recorded assumption
    # rather than an endless question. This is what makes the loop terminate.
    ledger.waive_exhausted()
    report = ledger.downgrade(report)
    spec_now = draft.to_spec()
    if _is_ready(draft, spec_now, report):
        return {
            "draft": draft,
            "lint": report,
            "spec": spec_now,
            "ledger": ledger,
            "status": "ready",
            "pending": None,
            "notices": _notices_with_waivers(state, ledger),
        }

    if round_no >= deps.max_rounds:
        return {
            "draft": draft,
            "lint": report,
            "spec": None,
            "ledger": ledger,
            "status": "exhausted",
            "pending": None,
            "notices": _notices_with_waivers(state, ledger)
            + [
                f"Stopped after {round_no} rounds without a clean spec. "
                "Generation stays refused; the remaining findings say what is missing."
            ],
        }

    batch = _ask_round(state, deps, draft, to_ask)

    if not batch.questions:
        # The interviewer had nothing left to ask but the spec is still not
        # clean. Stopping and saying so beats looping on an empty batch, which
        # looks to a caller exactly like a finished interview.
        return {
            "draft": draft,
            "lint": report,
            "spec": None,
            "ledger": ledger,
            "status": "exhausted",
            "pending": None,
            "notices": _notices_with_waivers(state, ledger)
            + [
                "The interviewer produced no further questions while the spec was "
                f"still incomplete (missing: {', '.join(draft.missing_fields()) or 'nothing'}). "
                "Generation stays refused."
            ],
        }

    return {
        "draft": draft,
        "lint": report,
        "ledger": ledger,
        "pending": batch,
        "round": round_no + 1,
        "status": "interviewing",
        "notices": _notices_with_waivers(state, ledger),
    }


def _notices_with_waivers(state: InterviewState, ledger: FindingLedger) -> list[str]:
    """Notices plus every waived finding, so nothing is accepted invisibly."""
    existing = [n for n in state.get("notices", []) if not n.startswith("Accepted without")]
    seen: set[str] = set()
    deduped = [n for n in existing + ledger.waiver_notes() if not (n in seen or seen.add(n))]
    return deduped


def _route(state: InterviewState) -> str:
    return "collect" if state.get("status") == "interviewing" else END


# Interview state carries our own Pydantic models, and the checkpointer has to
# be told they are safe to reconstruct. Without this every resume logs a warning
# per type, and a future LangGraph will refuse to deserialize them at all.
CHECKPOINT_TYPES = [
    ("ouroboros.inquisitor.findings", "FindingLedger"),
    ("ouroboros.inquisitor.findings", "FindingRecord"),
    ("ouroboros.models.patches", "FieldGroup"),
    ("ouroboros.models.interview", "SpecDraft"),
    ("ouroboros.models.interview", "Question"),
    ("ouroboros.models.interview", "QuestionOption"),
    ("ouroboros.models.interview", "QuestionBatch"),
    ("ouroboros.models.interview", "InterviewTurn"),
    ("ouroboros.models.interview", "Answer"),
    ("ouroboros.models.spec", "ProjectSpec"),
    ("ouroboros.models.spec", "StackProfile"),
    ("ouroboros.models.spec", "VerificationPlan"),
    ("ouroboros.models.spec", "Component"),
    ("ouroboros.models.spec", "Requirement"),
    ("ouroboros.models.spec", "LoopBoundaries"),
    ("ouroboros.models.spec", "Topology"),
    ("ouroboros.inquisitor.lint", "LintReport"),
    ("ouroboros.inquisitor.lint", "LintFinding"),
    ("ouroboros.inquisitor.lint", "Severity"),
]


def default_checkpointer():
    """An in-memory checkpointer that knows how to restore our state types."""
    try:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

        return MemorySaver(
            serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
        )
    except (ImportError, TypeError):
        # Older or newer LangGraph without this parameter: the warnings are
        # noisy but harmless, and an interview must not fail over them.
        return MemorySaver()


def build_interview_graph(deps: InquisitorDeps | None = None, checkpointer=None):
    """Compile the interview graph. A checkpointer is required for interrupts."""
    deps = deps or InquisitorDeps()
    graph = StateGraph(InterviewState)

    graph.add_node("open", lambda s: open_interview(s, deps))
    graph.add_node("collect", collect_answers)
    graph.add_node("integrate", lambda s: integrate(s, deps))
    graph.add_node("stack", lambda s: ensure_stack_coverage(s, deps))
    graph.add_node("assess", lambda s: assess(s, deps))

    graph.add_edge(START, "open")
    graph.add_edge("open", "collect")
    graph.add_edge("collect", "integrate")
    graph.add_edge("integrate", "stack")
    graph.add_edge("stack", "assess")
    graph.add_conditional_edges("assess", _route, {"collect": "collect", END: END})

    return graph.compile(checkpointer=checkpointer or default_checkpointer())


class InterviewSession:
    """Thread-scoped wrapper the web API talks to.

    `start` returns the first question batch; `answer` returns the next batch or
    the finished spec. All state lives in the checkpointer, so a session
    survives a page reload and can be resumed by id.
    """

    def __init__(self, thread_id: str, deps: InquisitorDeps | None = None, checkpointer=None):
        self.thread_id = thread_id
        self.graph = build_interview_graph(deps, checkpointer)
        self.config = {"configurable": {"thread_id": thread_id}}

    def start(self, brief: str) -> dict[str, Any]:
        self.graph.invoke({"brief": brief}, self.config)
        return self.snapshot()

    def answer(self, answers: Any) -> dict[str, Any]:
        self.graph.invoke(Command(resume=answers), self.config)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        state = self.graph.get_state(self.config)
        values: InterviewState = state.values
        pending: QuestionBatch | None = values.get("pending")
        draft = values.get("draft") or SpecDraft()
        lint = values.get("lint")
        spec = values.get("spec")

        return {
            "thread_id": self.thread_id,
            "status": values.get("status", "interviewing"),
            "round": values.get("round", 0),
            "questions": [q.model_dump() for q in (pending.questions if pending else [])],
            "rationale": pending.rationale if pending else "",
            "draft": draft.model_dump(mode="json"),
            "missing_fields": draft.missing_fields(),
            "lint": lint.model_dump(mode="json") if lint else None,
            "lint_summary": lint.summary() if lint else None,
            "spec": spec.model_dump(mode="json") if spec else None,
            "notices": values.get("notices", []),
            "transcript": [
                {"question": t.question.text, "answer": t.answer}
                for t in values.get("transcript", [])
            ],
        }


__all__ = [
    "InquisitorDeps",
    "InterviewSession",
    "InterviewState",
    "Question",
    "build_interview_graph",
]
