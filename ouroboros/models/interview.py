"""Interview data shapes: what the Inquisitor asks, and the draft it builds.

The draft mirrors ProjectSpec with every field optional. The interview works on
the draft; only a draft that survives the ambiguity lint is promoted to a real
ProjectSpec, which is what makes "refuse to generate" (D6) enforceable at the
type level rather than by convention.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ouroboros.models.spec import (
    Component,
    LoopBoundaries,
    ProjectSpec,
    Requirement,
    StackProfile,
    Topology,
    VerificationPlan,
)

QuestionKind = Literal["text", "single_select", "multi_select"]


class QuestionOption(BaseModel):
    label: str
    description: str = ""


class Question(BaseModel):
    """One interview question.

    `why_it_matters` is not decoration: requiring the model to name the spec
    field a question feeds keeps it from asking things it already knows or that
    change nothing downstream.
    """

    id: str
    header: str = Field(description="Two or three word label for the UI.")
    text: str
    kind: QuestionKind = "text"
    options: list[QuestionOption] = Field(default_factory=list)
    why_it_matters: str = Field(
        description="Which spec field this fills and what breaks without it."
    )
    targets: list[str] = Field(
        default_factory=list, description="Lint finding codes this question resolves."
    )


class QuestionBatch(BaseModel):
    """Two to three questions asked together, then answered together."""

    questions: list[Question] = Field(default_factory=list, max_length=4)
    rationale: str = ""


class Answer(BaseModel):
    question_id: str
    value: str


class InterviewTurn(BaseModel):
    question: Question
    answer: str


class SpecDraft(BaseModel):
    """A ProjectSpec under construction. Every field optional by design."""

    name: str | None = None
    slug: str | None = None
    one_line: str | None = None
    problem: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    stack: StackProfile | None = None
    verification: VerificationPlan | None = None
    components: list[Component] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    boundaries: LoopBoundaries = Field(default_factory=LoopBoundaries)
    glossary: dict[str, str] = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)

    def missing_fields(self) -> list[str]:
        """Required fields still empty, for steering the next question batch.

        This drives the interview's agenda, so anything the lint will refuse for
        has to appear here — otherwise the interviewer is told there is nothing
        left to ask while the spec is still unusable.
        """
        missing = [
            field
            for field in ("name", "one_line", "problem", "stack", "verification")
            if getattr(self, field) in (None, "")
        ]
        for field in ("success_criteria", "components", "requirements"):
            if not getattr(self, field):
                missing.append(field)

        # A component with no paths cannot fence a task, and the lint refuses
        # for it. Naming the specific components keeps the next question precise.
        unfenced = [c.name for c in self.components if not c.paths]
        if unfenced:
            missing.append(f"paths for components: {', '.join(unfenced)}")

        unverifiable = [r.id for r in self.requirements if not r.acceptance_criteria]
        if unverifiable:
            missing.append(
                f"acceptance criteria for: {', '.join(unverifiable)}"
            )

        return missing

    def to_spec(self) -> ProjectSpec | None:
        """Promote to a real spec, or None if the draft is still incomplete."""
        if self.missing_fields():
            return None
        try:
            return ProjectSpec(
                name=self.name,
                slug=self.slug or _slugify(self.name or ""),
                one_line=self.one_line,
                problem=self.problem,
                success_criteria=self.success_criteria,
                non_goals=self.non_goals,
                stack=self.stack,
                verification=self.verification,
                components=self.components,
                requirements=self.requirements,
                boundaries=self.boundaries,
                glossary=self.glossary,
                open_questions=self.open_questions,
            )
        except Exception:  # noqa: BLE001 - an invalid draft is simply not ready
            return None


def _slugify(name: str) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in name)
    return "-".join(part for part in cleaned.split("-") if part) or "project"


__all__ = [
    "Answer",
    "InterviewTurn",
    "Question",
    "QuestionBatch",
    "QuestionKind",
    "QuestionOption",
    "SpecDraft",
    "Topology",
]
