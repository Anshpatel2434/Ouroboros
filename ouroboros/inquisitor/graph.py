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
    draft = state.get("draft") or SpecDraft()
    asked = [t.question.text for t in state.get("transcript", [])]
    parts = [
        f"Project brief from the developer:\n{state.get('brief', '')}",
        f"\nCurrent draft spec:\n{draft.model_dump_json(indent=2)}",
        f"\nRequired fields still empty: {', '.join(draft.missing_fields()) or 'none'}",
    ]
    if findings_text:
        parts.append(
            "\nThe ambiguity lint refuses to generate until these are resolved. "
            "Ask the questions that resolve them:\n" + findings_text
        )
    if asked:
        parts.append("\nAlready asked (do not repeat):\n" + "\n".join(f"- {q}" for q in asked))
    parts.append(
        "\nRelevant harness-engineering guidance:\n"
        + _corpus_context(deps, state.get("brief", ""))
    )
    parts.append(f"\nAsk round {state.get('round', 0) + 1} of at most {deps.max_rounds}.")
    return "\n".join(parts)


def _findings_text(report: LintReport | None) -> str:
    if report is None:
        return ""
    return "\n".join(
        f"- [{f.code}] {f.location}: {f.evidence} -> {f.rectification}"
        for f in report.errors
    )


def open_interview(state: InterviewState, deps: InquisitorDeps) -> dict[str, Any]:
    batch = deps.llm.structured(
        QuestionBatch, system=INTERVIEWER, user=_ask_prompt(state, deps)
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

    updated = deps.llm.structured(
        SpecDraft,
        system=INTEGRATOR,
        user=(
            f"Current draft:\n{draft.model_dump_json(indent=2)}\n\n"
            f"New answers:\n" + "\n\n".join(exchange_lines) +
            "\n\nReturn the complete updated draft."
        ),
    )
    return {"draft": updated, "transcript": turns, "answers": []}


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
    )
    return {
        "lint": report,
        "pending": batch,
        "round": round_no + 1,
        "status": "interviewing",
    }


def _route(state: InterviewState) -> str:
    return "collect" if state.get("status") == "interviewing" else END


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

    return graph.compile(checkpointer=checkpointer or MemorySaver())


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
