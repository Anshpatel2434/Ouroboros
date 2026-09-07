"""Targeted extraction: one answer, one field group, one tiny schema.

Replaces the whole-draft rewrite. Each call sees only the part of the spec it is
allowed to touch and returns only that part, so no other field can be lost no
matter what the model does. The cost is more calls; each is small, fast, and
cheap, which is the right trade for a model that is unreliable on large nested
outputs and perfectly good on small ones.
"""

from __future__ import annotations

from pydantic import BaseModel

from ouroboros.llm.client import LLM
from ouroboros.models.interview import SpecDraft
from ouroboros.models.patches import (
    ComponentsPatch,
    FieldGroup,
    GlossaryPatch,
    GoalsPatch,
    IdentityPatch,
    RequirementsPatch,
    StackPatch,
    VerificationPatch,
)

EXTRACTOR = """\
You extract one specific part of a project specification from an interview \
exchange. You are given the current value of that part and the developer's \
latest answers.

Return the updated value of THAT PART ONLY. Nothing else in the specification \
exists for you.

Rules:
- Carry forward everything still true. Returning a field empty deletes it.
- Never invent a fact the developer has not stated. If something is unknown, \
leave it unset rather than filling it in.
- Prefer the developer's exact words for names, commands and values.
- If the answers say nothing about this part, return the current value unchanged."""


GROUP_BRIEF = {
    FieldGroup.IDENTITY: (
        "The project's identity: name, repo-safe slug, one-line summary, and the "
        "problem it solves and for whom."
    ),
    FieldGroup.GOALS: (
        "Success criteria (how the finished project is judged) and non-goals "
        "(what it must explicitly not do). Both are lists of short statements."
    ),
    FieldGroup.STACK: (
        "The technology: language and version, framework, package manager, "
        "database, key libraries. Use the developer's exact choices; a guessed "
        "package manager makes every generated command wrong. The version that "
        "matters is the one the project is pinned to and run with — for "
        "JavaScript or TypeScript that is the Node version (22.x) or the "
        "TypeScript version, never an ECMAScript edition; for Python the "
        "interpreter version. Never ask which ECMAScript edition to target."
    ),
    FieldGroup.VERIFICATION: (
        "The commands that decide whether work is acceptable: install and test "
        "are required, lint, typecheck, build and smoke are optional. These are "
        "run verbatim, so they must be real commands for this stack."
    ),
    FieldGroup.COMPONENTS: (
        "The named parts of the system, each with a one-sentence responsibility "
        "and the files or directories it owns. Those paths become the fence that "
        "stops the coding agent editing outside its task, so every component "
        "needs at least one. Where the developer has not said, use the "
        "conventional location for the stack."
    ),
    FieldGroup.REQUIREMENTS: (
        "What the software must do. Each requirement has a stable id (R-001 "
        "style), a one-sentence statement, and at least one acceptance criterion "
        "a script could check: a status code, an exact output, a file that "
        "exists, a threshold with a number. Keep each small enough for a single "
        "commit."
    ),
    FieldGroup.GLOSSARY: (
        "Definitions of domain terms used in the requirements. Extract a term "
        "and its definition whenever an answer explains what something MEANS. "
        "Return every term already defined plus any new ones; a term that "
        "disappears will be asked about again."
    ),
}


def current_value(draft: SpecDraft, group: FieldGroup) -> BaseModel:
    """The patch-shaped view of what the draft already holds for this group."""
    if group is FieldGroup.IDENTITY:
        return IdentityPatch(
            name=draft.name, slug=draft.slug, one_line=draft.one_line, problem=draft.problem
        )
    if group is FieldGroup.GOALS:
        return GoalsPatch(
            success_criteria=list(draft.success_criteria), non_goals=list(draft.non_goals)
        )
    if group is FieldGroup.STACK:
        return StackPatch(stack=draft.stack)
    if group is FieldGroup.VERIFICATION:
        return VerificationPatch(verification=draft.verification)
    if group is FieldGroup.COMPONENTS:
        return ComponentsPatch(components=list(draft.components))
    if group is FieldGroup.REQUIREMENTS:
        return RequirementsPatch(requirements=list(draft.requirements))
    return GlossaryPatch(
        entries=[{"term": t, "definition": d} for t, d in draft.glossary.items()]
    )


def apply_patch(draft: SpecDraft, group: FieldGroup, patch: BaseModel) -> SpecDraft:
    """Fold one group's patch into the draft, leaving every other group alone."""
    updated = draft.model_copy(deep=True)

    if group is FieldGroup.IDENTITY and isinstance(patch, IdentityPatch):
        for field in ("name", "slug", "one_line", "problem"):
            value = (getattr(patch, field) or "").strip()
            if value:
                setattr(updated, field, value)

    elif group is FieldGroup.GOALS and isinstance(patch, GoalsPatch):
        if patch.success_criteria:
            updated.success_criteria = patch.success_criteria
        if patch.non_goals:
            updated.non_goals = patch.non_goals

    elif group is FieldGroup.STACK and isinstance(patch, StackPatch):
        if patch.stack is not None:
            covered = updated.stack.corpus_covered if updated.stack else False
            updated.stack = patch.stack
            # Research coverage is ours to track, not something to re-derive.
            updated.stack.corpus_covered = patch.stack.corpus_covered or covered

    elif group is FieldGroup.VERIFICATION and isinstance(patch, VerificationPatch):
        if patch.verification is not None:
            previous = updated.verification
            updated.verification = patch.verification
            if previous is not None:
                for field in ("install", "test", "lint", "typecheck", "build", "smoke"):
                    if not (getattr(patch.verification, field) or "").strip():
                        setattr(updated.verification, field, getattr(previous, field))

    elif group is FieldGroup.COMPONENTS and isinstance(patch, ComponentsPatch):
        updated.components = _merge_by(
            updated.components, patch.components, key="name", remove=patch.remove_names
        )

    elif group is FieldGroup.REQUIREMENTS and isinstance(patch, RequirementsPatch):
        updated.requirements = _merge_by(
            updated.requirements, patch.requirements, key="id", remove=patch.remove_ids
        )

    elif group is FieldGroup.GLOSSARY and isinstance(patch, GlossaryPatch):
        for entry in patch.entries:
            if entry.term.strip() and entry.definition.strip():
                updated.glossary[entry.term.strip()] = entry.definition.strip()

    return updated


def _merge_by(existing: list, incoming: list, key: str, remove: list[str]) -> list:
    """Merge lists by identity: add new entries, update matches, keep the rest.

    A spec is built up across rounds — requirements are elicited a component at
    a time — so replacing the list would delete everything established earlier
    every time a later round talked about something else. Removal stays possible
    but has to be asked for explicitly.
    """
    dropped = {value.strip() for value in remove if value and value.strip()}
    merged = {getattr(item, key): item for item in existing}
    for item in incoming:
        merged[getattr(item, key)] = item
    return [item for identity, item in merged.items() if identity not in dropped]


def extract_group(
    llm: LLM, draft: SpecDraft, group: FieldGroup, exchange: str, guidance: str = ""
) -> SpecDraft:
    """Ask for one field group and apply it. Nothing else can change."""
    from ouroboros.models.patches import PATCH_SCHEMAS

    schema = PATCH_SCHEMAS[group]
    existing = current_value(draft, group)

    patch = llm.structured(
        schema,
        system=EXTRACTOR,
        user=(
            f"You are extracting: {group.value}\n{GROUP_BRIEF[group]}\n\n"
            f"Current value:\n{existing.model_dump_json(indent=2)}\n\n"
            f"The developer's latest answers:\n{exchange}"
            + (f"\n\nAlso apply this correction:\n{guidance}" if guidance else "")
            + f"\n\nReturn the updated {group.value}."
        ),
        role="patch",
    )
    return apply_patch(draft, group, patch)
