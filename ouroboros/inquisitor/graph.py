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
from ouroboros.inquisitor.lint import LintReport
from ouroboros.inquisitor.prompts import INTEGRATOR, INTERVIEWER
from ouroboros.inquisitor.research import ensure_playbook
from ouroboros.inquisitor.semantic import full_lint
from ouroboros.llm.client import LLM, default_llm
from ouroboros.models.interview import (
    InterviewTurn,
    Question,
    QuestionBatch,
    SpecDraft,
)
from ouroboros.models.spec import ProjectSpec

Status = Literal["interviewing", "ready", "exhausted"]

MAX_ROUNDS = 12


class InterviewState(TypedDict, total=False):
    brief: str
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


def _ask_prompt(state: InterviewState, deps: InquisitorDeps, findings_text: str = "") -> str:
    from ouroboros.llm.budget import trim_to_tokens
    from ouroboros.llm.client import limits_for

    draft = state.get("draft") or SpecDraft()
    asked = [t.question.text for t in state.get("transcript", [])]
    missing = draft.missing_fields()

    # Settled fields go in as a short list rather than buried in the draft JSON.
    # An early version passed only the JSON and the interviewer asked for the
    # project name three rounds running: what is already known has to be
    # impossible to miss.
    settled = _settled_summary(draft)

    parts = [f"Project brief from the developer:\n{state.get('brief', '')}"]

    if settled:
        parts.append(
            "\nALREADY SETTLED — do not ask about any of these again:\n" + settled
        )

    if missing:
        parts.append(
            "\nSTILL MISSING — this round's agenda. Ask only about these:\n"
            + "\n".join(f"- {field}" for field in missing)
        )
    elif not findings_text:
        parts.append(
            "\nEvery required field is filled. Ask only what would sharpen a "
            "requirement that is still too vague to verify."
        )

    if findings_text:
        parts.append(
            "\nThe ambiguity lint refuses to generate until these are resolved. "
            "Ask the questions that resolve them — you must return at least one "
            "question while any of these stand:\n" + findings_text
        )

    # The draft is the biggest thing here and the least load-bearing now that
    # the settled list carries the same information, so it is trimmed hardest.
    draft_json, _ = trim_to_tokens(
        draft.model_dump_json(indent=2),
        int(limits_for().prompt_budget("questions") * 0.35),
    )
    parts.append(f"\nFull draft for reference:\n{draft_json}")

    if asked:
        recent = asked[-12:]
        parts.append(
            "\nQuestions already asked. Asking any of these again wastes the "
            "developer's time:\n" + "\n".join(f"- {q}" for q in recent)
        )

    parts.append(
        "\nRelevant harness-engineering guidance:\n"
        + _corpus_context(deps, state.get("brief", ""))
    )
    parts.append(f"\nAsk round {state.get('round', 0) + 1} of at most {deps.max_rounds}.")
    return "\n".join(parts)


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


def open_interview(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    batch = deps.llm.structured(
        QuestionBatch, system=INTERVIEWER, user=_ask_prompt(state, deps), role="questions"
    )
    return {
        "draft": state.get("draft") or SpecDraft(),
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
    draft = state.get("draft") or SpecDraft()
    pending = state.get("pending")
    by_id = {q.id: q for q in (pending.questions if pending else [])}

    turns = list(state.get("transcript", []))
    exchange_lines = []
    for answer in state.get("answers", []):
        question = by_id.get(answer["question_id"])
        if question is None:
            continue
        turns.append(InterviewTurn(question=question, answer=answer["value"]))
        exchange_lines.append(f"Q: {question.text}\nA: {answer['value']}")

    # Findings whose fix is a spec edit — a redundant requirement, a duplicated
    # statement — cannot be resolved by asking the developer anything. A live
    # interview looped for four rounds asking yes/no questions while the lint
    # kept repeating "R-009 is redundant with R-006, remove it". The integrator
    # is the only step that can actually apply that fix, so it sees them too.
    outstanding = _findings_text(state.get("lint"))
    structural_note = (
        "\n\nThe ambiguity lint is currently refusing for these reasons. Where a "
        "finding asks you to remove, merge, or restructure something in the spec, "
        "DO IT NOW as part of this update — those cannot be fixed by asking the "
        "developer another question. Where it asks for information you do not "
        "have, leave it alone; it will be asked.\n" + outstanding
        if outstanding
        else ""
    )

    updated = deps.llm.structured(
        SpecDraft,
        system=INTEGRATOR,
        user=(
            f"Current draft:\n{draft.model_dump_json(indent=2)}\n\n"
            f"New answers:\n" + "\n\n".join(exchange_lines) +
            structural_note +
            "\n\nReturn the complete updated draft."
        ),
        role="draft",
    )
    # Fold rather than replace: an omitted field means "unchanged", not "deleted".
    return {"draft": draft.merged_with(updated), "transcript": turns, "answers": []}


def ensure_stack_coverage(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    """Research an unknown stack once, write it back, and unblock the lint."""
    draft = state.get("draft") or SpecDraft()
    notices = list(state.get("notices", []))

    if draft.stack is None or draft.stack.corpus_covered:
        return {"notices": notices}

    playbook, researched = ensure_playbook(
        deps.llm, deps.retriever, draft.stack, root=deps.corpus_root
    )
    draft.stack.corpus_covered = True

    if researched and playbook is not None:
        notices.append(
            f"Researched {draft.stack.language} "
            f"{draft.stack.framework or ''}".strip() + " and added it to the corpus."
        )
        # A researched playbook is a better source of verification commands than
        # anything the developer half-remembers, but it never overrides what they
        # explicitly told us.
        if draft.verification is None:
            draft.verification = playbook.to_verification()

    return {"draft": draft, "notices": notices}


def assess(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    draft = state.get("draft") or SpecDraft()
    round_no = state.get("round", 1)
    spec = draft.to_spec()

    report: LintReport | None = None
    if spec is not None:
        report = full_lint(deps.llm, spec)
        if report.passed:
            return {"lint": report, "spec": spec, "status": "ready", "pending": None}

    if round_no >= deps.max_rounds:
        return {
            "lint": report,
            "spec": None,
            "status": "exhausted",
            "pending": None,
            "notices": list(state.get("notices", []))
            + [
                f"Stopped after {round_no} rounds without a clean spec. "
                "Generation stays refused; the remaining findings say what is missing."
            ],
        }

    batch = deps.llm.structured(
        QuestionBatch,
        system=INTERVIEWER,
        user=_ask_prompt(state, deps, _findings_text(report)),
        role="questions",
    )

    if not batch.questions:
        # The interviewer had nothing left to ask but the spec is still not
        # clean. Stopping and saying so beats looping on an empty batch, which
        # looks to a caller exactly like a finished interview.
        return {
            "lint": report,
            "spec": None,
            "status": "exhausted",
            "pending": None,
            "notices": list(state.get("notices", []))
            + [
                "The interviewer produced no further questions while the spec was "
                f"still incomplete (missing: {', '.join(draft.missing_fields()) or 'nothing'}). "
                "Generation stays refused."
            ],
        }

    return {
        "lint": report,
        "pending": batch,
        "round": round_no + 1,
        "status": "interviewing",
    }


def _route(state: InterviewState) -> str:
    return "collect" if state.get("status") == "interviewing" else END


# Interview state carries our own Pydantic models, and the checkpointer has to
# be told they are safe to reconstruct. Without this every resume logs a warning
# per type, and a future LangGraph will refuse to deserialize them at all.
CHECKPOINT_TYPES = [
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
