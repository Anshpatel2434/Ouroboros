"""Small, single-purpose schemas the interview extracts into.

The interview used to ask a model to return the entire draft every round. That
made every omission a deletion, put a thirteen-field nested object behind one
call, and gave a small model every opportunity to flatten or drop something.
Losing the project name at round five was not the model failing at a reasonable
task; it was an unreasonable task.

So the draft is never rewritten. Each answer is extracted into exactly one of
these patches — a handful of fields, one job — and applied to the field group it
belongs to. A field nobody asked about cannot change, which is a structural
guarantee rather than a hope.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ouroboros.models.spec import (
    Component,
    Requirement,
    StackProfile,
    VerificationPlan,
)


class FieldGroup(str, Enum):
    """The parts of a spec a single question can be about."""

    IDENTITY = "identity"
    GOALS = "goals"
    STACK = "stack"
    VERIFICATION = "verification"
    COMPONENTS = "components"
    REQUIREMENTS = "requirements"
    GLOSSARY = "glossary"


class IdentityPatch(BaseModel):
    name: str | None = Field(default=None, description="Short project name.")
    slug: str | None = Field(default=None, description="Repo-safe, kebab-case.")
    one_line: str | None = Field(default=None, description="One sentence.")
    problem: str | None = Field(default=None, description="The problem, for whom.")


class GoalsPatch(BaseModel):
    success_criteria: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)


class StackPatch(BaseModel):
    stack: StackProfile | None = None


class VerificationPatch(BaseModel):
    verification: VerificationPlan | None = None


class ComponentsPatch(BaseModel):
    """Components to add or update, matched by name."""

    components: list[Component] = Field(default_factory=list)
    remove_names: list[str] = Field(
        default_factory=list, description="Components to delete outright."
    )


class RequirementsPatch(BaseModel):
    """Requirements to add or update, matched by id.

    Additive by default. A spec is built up over several rounds — asked about
    one component at a time — so a patch that replaced the list would delete
    everything established earlier. Deleting is possible, but only by saying so
    in remove_ids, which is what lets a redundant requirement actually go.
    """

    requirements: list[Requirement] = Field(default_factory=list)
    remove_ids: list[str] = Field(
        default_factory=list, description="Requirement ids to delete outright."
    )


class GlossaryEntry(BaseModel):
    """A term and its definition.

    A list of pairs rather than a mapping: OpenAI's strict json_schema mode
    rejects dict-typed fields outright, and a small model handles a flat list of
    two-field objects far more reliably than a free-form object.
    """

    term: str
    definition: str


class GlossaryPatch(BaseModel):
    entries: list[GlossaryEntry] = Field(default_factory=list)


PATCH_SCHEMAS: dict[FieldGroup, type[BaseModel]] = {
    FieldGroup.IDENTITY: IdentityPatch,
    FieldGroup.GOALS: GoalsPatch,
    FieldGroup.STACK: StackPatch,
    FieldGroup.VERIFICATION: VerificationPatch,
    FieldGroup.COMPONENTS: ComponentsPatch,
    FieldGroup.REQUIREMENTS: RequirementsPatch,
    FieldGroup.GLOSSARY: GlossaryPatch,
}
