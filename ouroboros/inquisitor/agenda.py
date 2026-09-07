"""Deciding what to ask about, deterministically.

The interviewer used to choose both the wording of a question and which part of
the spec its answer belonged to. The second decision is not a judgement call —
the draft plainly shows which parts are empty — and leaving it to the model cost
an entire ten-round interview in which every answer was good and almost none of
them landed.

So the system picks the field groups from the draft and the outstanding
findings, and the model is asked only to phrase one question about one group.
"""

from __future__ import annotations

from ouroboros.inquisitor.findings import FindingRecord
from ouroboros.models.interview import SpecDraft
from ouroboros.models.patches import FieldGroup

MAX_QUESTIONS_PER_ROUND = 3

# Which group answers a given gap. Order matters: identity and stack first,
# because later questions read better once the project has a name and a stack.
_MISSING_TO_GROUP: list[tuple[str, FieldGroup]] = [
    ("name", FieldGroup.IDENTITY),
    ("one_line", FieldGroup.IDENTITY),
    ("problem", FieldGroup.IDENTITY),
    ("stack", FieldGroup.STACK),
    ("verification", FieldGroup.VERIFICATION),
    ("success_criteria", FieldGroup.GOALS),
    ("components", FieldGroup.COMPONENTS),
    ("paths for components", FieldGroup.COMPONENTS),
    ("requirements", FieldGroup.REQUIREMENTS),
    ("acceptance criteria for", FieldGroup.REQUIREMENTS),
]

GROUP_ORDER = [
    FieldGroup.IDENTITY,
    FieldGroup.STACK,
    FieldGroup.VERIFICATION,
    FieldGroup.GOALS,
    FieldGroup.COMPONENTS,
    FieldGroup.REQUIREMENTS,
    FieldGroup.GLOSSARY,
]


def groups_for_missing(missing: list[str]) -> list[FieldGroup]:
    """Field groups implied by the draft's empty required fields."""
    groups: list[FieldGroup] = []
    for gap in missing:
        for token, group in _MISSING_TO_GROUP:
            if gap.startswith(token) and group not in groups:
                groups.append(group)
                break
    return groups


def plan_round(
    draft: SpecDraft, to_ask: list[FindingRecord]
) -> list[tuple[FieldGroup, str]]:
    """The groups to ask about this round, each with why it is on the agenda.

    Gaps come first — a finding about requirements is noise while the stack is
    still unknown — and the round is capped so the developer answers a few
    focused questions rather than a survey.
    """
    planned: list[tuple[FieldGroup, str]] = []
    seen: set[FieldGroup] = set()

    missing = draft.missing_fields()
    for group in groups_for_missing(missing):
        if group not in seen:
            reasons = [m for m in missing if group in groups_for_missing([m])]
            planned.append((group, "Still empty: " + "; ".join(reasons)))
            seen.add(group)

    for record in to_ask:
        if record.group not in seen:
            planned.append((record.group, record.as_instruction()))
            seen.add(record.group)

    planned.sort(key=lambda item: GROUP_ORDER.index(item[0]))
    return planned[:MAX_QUESTIONS_PER_ROUND]
