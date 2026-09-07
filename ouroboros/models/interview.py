"""Interview data shapes: what the Inquisitor asks, and the draft it builds.

The draft mirrors ProjectSpec with every field optional. The interview works on
the draft; only a draft that survives the ambiguity lint is promoted to a real
ProjectSpec, which is what makes "refuse to generate" (D6) enforceable at the
type level rather than by convention.
"""

from __future__ import annotations

import re
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from ouroboros.models.patches import FieldGroup
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
    field_group: FieldGroup = Field(
        default=FieldGroup.REQUIREMENTS,
        description="Which part of the spec this question's answer belongs to. "
        "The answer is extracted into that part and nothing else, so a wrong "
        "group means the answer lands nowhere.",
    )
    targets: list[str] = Field(
        default_factory=list, description="Lint finding codes this question resolves."
    )


class SingleQuestion(BaseModel):
    """One question about a field group the system has already chosen.

    The interviewer used to tag its own questions with a field group and route
    the answer itself. gpt-4o-mini simply omitted the tag, every answer fell
    through to the default group, and ten rounds of good answers landed nowhere.
    The system knows which part of the spec is empty, so it assigns the group and
    asks only for the wording. A routing decision nobody makes cannot be wrong.
    """

    header: str = Field(description="Two or three word label for the UI.")
    text: str = Field(description="The question itself.")
    kind: QuestionKind = "text"
    options: list[QuestionOption] = Field(
        default_factory=list,
        description="Concrete choices, when the sane answers are few. Otherwise empty.",
    )
    why_it_matters: str = Field(
        description="What this fills and what breaks downstream without it."
    )


# The space after the marker is load-bearing. Without it, "TypeScript 4.5, 4.6,
# 4.7" parses as options "5", "6", "7" — a version list rendered to the
# developer as nonsense, which a live interview did exactly once before this.
_ENUMERATION = re.compile(
    r"(?:^|[\s:;,])(\d)[).]\s+([^,;\n]{2,60}?)(?=\s*(?:,|;|\s\d[).]\s|$))"
)


def options_from_prose(text: str) -> tuple[str, list[QuestionOption]]:
    """Pull an inline list of choices out of a question and make it clickable.

    Models keep writing "Please choose one of the following: 1) npm, 2) yarn,
    3) pnpm" as prose. The UI can render real options, so a developer ends up
    typing an answer to something they should have clicked, and the free-text
    answer then extracts less cleanly. The enumeration is unambiguous, so it is
    parsed out rather than asked for again.
    """
    matches = list(_ENUMERATION.finditer(text))
    if len(matches) < 2:
        return text, []

    numbers = [int(m.group(1)) for m in matches]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return text, []  # Not a clean run; leave it alone.

    options = [
        QuestionOption(label=m.group(2).strip().rstrip(".").strip())
        for m in matches
    ]
    if any(not o.label for o in options):
        return text, []

    stem = text[: matches[0].start()].rstrip()
    for tail in (
        "Please choose one of the following:", "Please select one:",
        "Choose one of the following:", "Select one:", "as follows:",
        "the following:", "one of:",
    ):
        if stem.endswith(tail):
            stem = stem[: -len(tail)].rstrip()
    question = (stem or text).rstrip(":,; ")
    return (question if question.endswith("?") else question + "?"), options


_PLURAL_ASK = re.compile(
    r"all that apply|select at least|choose at least|one or more|"
    r"which of the following|any that|select all",
    re.IGNORECASE,
)


def infer_kind(text: str, options: list[QuestionOption], stated: str) -> str:
    """Decide single- or multi-select from the wording when the model did not.

    Models leave `kind` as "text" while supplying options and asking for several
    of them. Rendered as radio buttons, a question that says "select at least
    install and test" cannot be answered at all.
    """
    if not options:
        return "text"
    if stated in ("single_select", "multi_select"):
        return stated
    return "multi_select" if _PLURAL_ASK.search(text) else "single_select"


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


def _unflatten_objects(value: object, keys: set[str], start_key: str) -> object:
    """Rebuild objects a model flattened into a list of alternating key/value items.

    Small models intermittently return `["id", "R-007", "statement", "...",
    "priority", "must"]` where a list of objects belongs. Pydantic rejects it and
    the whole interview round dies, losing work the developer already did. The
    shape is unambiguous enough to repair: a known field name followed by its
    value, with `start_key` opening each new object.
    """
    if not isinstance(value, list) or not value:
        return value
    if not any(isinstance(item, str) for item in value):
        return value

    rebuilt: list[dict] = []
    current: dict = {}
    index = 0
    while index < len(value) - 1:
        key = value[index]
        if not isinstance(key, str) or key not in keys:
            return value  # Not the shape we know how to repair; leave it alone.
        if key == start_key and current:
            rebuilt.append(current)
            current = {}
        current[key] = value[index + 1]
        index += 2

    if current:
        rebuilt.append(current)
    return rebuilt or value


class SpecDraft(BaseModel):
    """A ProjectSpec under construction. Every field optional by design."""

    @field_validator("requirements", "components", mode="before")
    @classmethod
    def _repair_flattened(cls, value, info):
        keys = (
            {"id", "statement", "acceptance_criteria", "priority", "depends_on"}
            if info.field_name == "requirements"
            else {"name", "responsibility", "paths"}
        )
        start = "id" if info.field_name == "requirements" else "name"
        return _unflatten_objects(value, keys, start)

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

    def merged_with(self, update: "SpecDraft") -> "SpecDraft":
        """Fold a model's returned draft over this one, never losing what it omitted.

        The integrator is asked for the complete draft each round, which makes
        every omission a silent deletion. A live interview on a small model
        regressed from a nearly complete spec to asking for the project name
        again — four rounds of work gone, with nothing in the transcript to
        explain it.

        So an omission is treated as "unchanged" rather than "deleted". Real
        edits still land: a field the model fills wins, and a list it returns
        non-empty replaces the old one, which is what lets a redundant
        requirement actually be removed.
        """
        merged = update.model_copy(deep=True)

        for field in ("name", "slug", "one_line", "problem"):
            if not (getattr(update, field) or "").strip():
                setattr(merged, field, getattr(self, field))

        for field in ("success_criteria", "non_goals", "components", "requirements"):
            if not getattr(update, field):
                setattr(merged, field, getattr(self, field))

        if update.stack is None:
            merged.stack = self.stack
        elif self.stack is not None:
            # Keep a researched-coverage flag the model would not know to set.
            merged.stack.corpus_covered = (
                update.stack.corpus_covered or self.stack.corpus_covered
            )

        if update.verification is None:
            merged.verification = self.verification
        elif self.verification is not None:
            for field in ("install", "test", "lint", "typecheck", "build", "smoke"):
                if not (getattr(update.verification, field) or "").strip():
                    setattr(merged.verification, field, getattr(self.verification, field))

        # Definitions accumulate; a later round never drops an earlier term.
        merged.glossary = {**self.glossary, **update.glossary}

        return merged

    # What "enough" means. Deliberately modest so a genuinely small tool still
    # finishes, while a project of any real size keeps being asked about.
    MIN_SUCCESS_CRITERIA: ClassVar[int] = 2
    MIN_REQUIREMENTS: ClassVar[int] = 3

    def _insufficient(self) -> list[str]:
        """Parts that exist but are too thin to describe the project."""
        gaps: list[str] = []

        if not self.success_criteria:
            gaps.append("success_criteria")
        elif len(self.success_criteria) < self.MIN_SUCCESS_CRITERIA:
            gaps.append(
                f"success_criteria: only {len(self.success_criteria)} recorded, "
                f"need at least {self.MIN_SUCCESS_CRITERIA}"
            )

        if not self.non_goals:
            gaps.append("non_goals: nothing is out of scope yet")

        if not self.components:
            gaps.append("components")

        # A requirement per component, and never fewer than the floor. A spec
        # with four components and one requirement describes almost nothing.
        target = max(self.MIN_REQUIREMENTS, len(self.components))
        if not self.requirements:
            gaps.append("requirements")
        elif len(self.requirements) < target:
            uncovered = self.components_without_requirements()
            detail = (
                f" — nothing yet for: {', '.join(uncovered)}" if uncovered else ""
            )
            gaps.append(
                f"requirements: only {len(self.requirements)} of at least "
                f"{target}{detail}"
            )

        return gaps

    def components_without_requirements(self) -> list[str]:
        """Components no requirement appears to mention.

        A name-match heuristic, used only to aim the next question. Being wrong
        costs one slightly redundant question, never a lost field.
        """
        text = " ".join(
            f"{r.statement} {' '.join(r.acceptance_criteria)}" for r in self.requirements
        ).lower()
        return [c.name for c in self.components if c.name.lower() not in text]

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

        # A verification object of empty strings is "present" but useless. A live
        # interview produced exactly that and the agenda reported nothing missing,
        # so the interviewer never asked for the commands.
        if self.stack is not None:
            blank_stack = [
                label
                for label, value in (
                    ("language", self.stack.language),
                    ("language version", self.stack.language_version),
                    ("package manager", self.stack.package_manager),
                )
                if not (value or "").strip()
            ]
            if blank_stack:
                missing.append("stack " + ", ".join(blank_stack))

        if self.verification is not None:
            blank = [
                label
                for label in ("install", "test")
                if not (getattr(self.verification, label) or "").strip()
            ]
            if blank:
                missing.append(f"verification commands: {', '.join(blank)}")
        # Presence is not sufficiency, and treating it as such is why every
        # interview produced a thin spec. One vague line satisfied
        # "success_criteria", one requirement satisfied "requirements", the
        # agenda went quiet, and the interview ended with a spec that could not
        # describe the project. "An e-commerce site for shoes" cannot be one
        # requirement, and nothing in the old agenda knew that.
        missing.extend(self._insufficient())

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
