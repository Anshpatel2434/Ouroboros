"""The finding ledger — what makes the interview terminate.

The old loop had no memory of findings. Each round re-linted, got the same
complaint back, turned it into another question, and started over. A live
interview spent four rounds on "R-009 is redundant with R-006, remove it",
because the only response the architecture knew how to make was to ask the
developer something, and no answer can delete a requirement.

Here every finding is tracked by fingerprint and escalated:

    1st sighting  -> try the resolution that fits it (edit the spec, or ask)
    2nd sighting  -> try the other one
    3rd sighting  -> waive it, recorded as an explicit assumption

That ladder is the termination proof. A finding cannot be seen a fourth time,
so the interview cannot loop, and nothing is silently dropped: a waiver is
visible to the developer and travels into the generated spec.md.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum

from pydantic import BaseModel, Field

from ouroboros.inquisitor.lint import LintFinding, LintReport, Severity
from ouroboros.models.patches import FieldGroup

MAX_ATTEMPTS = 2  # After this many sightings the finding is waived.


class Resolution(str, Enum):
    """How a finding can actually be made to go away."""

    EDIT = "edit"  # We can fix the spec ourselves.
    ASK = "ask"  # Only the developer knows.


# Which findings are spec surgery rather than missing information. Getting this
# wrong is not fatal — the escalation ladder tries the other route next round —
# but starting on the right one saves a round.
EDITABLE_CODES = {
    "LABEL_AS_COMMAND",
    "MISMATCHED_TOOLCHAIN",
    "MISSING_VERIFICATION_COMMAND",
    "EMPTY_VERIFICATION_COMMAND",
    "INCOMPLETE_STACK",
    "CONTRADICTION",
    "DANGLING_DEPENDENCY",
    "SELF_DEPENDENCY",
    "DUPLICATE_REQUIREMENT_ID",
    "COMPONENT_WITHOUT_PATHS",
    "UNDEFINED_TERM",
    "PLACEHOLDER",
}

# Which part of the spec a finding lives in, so an edit goes to the right
# extractor instead of rewriting everything.
CODE_GROUPS = {
    "NO_ACCEPTANCE_CRITERIA": FieldGroup.REQUIREMENTS,
    "UNVERIFIABLE_CRITERION": FieldGroup.REQUIREMENTS,
    "UNBUILDABLE_CRITERION": FieldGroup.REQUIREMENTS,
    "DANGLING_DEPENDENCY": FieldGroup.REQUIREMENTS,
    "SELF_DEPENDENCY": FieldGroup.REQUIREMENTS,
    "DUPLICATE_REQUIREMENT_ID": FieldGroup.REQUIREMENTS,
    "NO_REQUIREMENTS": FieldGroup.REQUIREMENTS,
    "CONTRADICTION": FieldGroup.REQUIREMENTS,
    "COVERAGE_HOLE": FieldGroup.REQUIREMENTS,
    "COMPONENT_WITHOUT_PATHS": FieldGroup.COMPONENTS,
    "NO_COMPONENTS": FieldGroup.COMPONENTS,
    "UNDEFINED_TERM": FieldGroup.GLOSSARY,
    "NO_SUCCESS_CRITERIA": FieldGroup.GOALS,
    "NO_NON_GOALS": FieldGroup.GOALS,
    "LABEL_AS_COMMAND": FieldGroup.VERIFICATION,
    "MISMATCHED_TOOLCHAIN": FieldGroup.VERIFICATION,
    "INCOMPLETE_STACK": FieldGroup.STACK,
    "MISSING_VERIFICATION_COMMAND": FieldGroup.VERIFICATION,
    "EMPTY_VERIFICATION_COMMAND": FieldGroup.VERIFICATION,
    "NO_SMOKE_CHECK": FieldGroup.VERIFICATION,
    "STACK_NOT_RESEARCHED": FieldGroup.STACK,
    "PLACEHOLDER": FieldGroup.IDENTITY,
}


# What a finding is *about*: requirement and task ids, quoted terms, paths.
_IDENTIFIERS = re.compile(
    r"\b[A-Za-z]-\d+\b"          # R-009, T-001
    r"|'[^']{1,40}'|\"[^\"]{1,40}\""  # 'malformed URL'
    r"|\b[\w./-]+\.[a-z]{1,5}\b"  # pyproject.toml, src/app/cli.py
)


def fingerprint(finding: LintFinding) -> str:
    """Stable identity for a finding across rounds.

    Keyed on the entities the finding names rather than its prose. A judge
    rewords the same complaint every time it makes it — "R-009 duplicates R-006"
    and "Requirement R-009 is redundant: it duplicates R-006" are one finding —
    and word-level keying made each round look like a brand new problem, so
    nothing ever escalated and the interview could loop forever.
    """
    subjects = {
        match.group(0).strip("'\"").lower()
        for match in _IDENTIFIERS.finditer(finding.evidence)
    }
    if not subjects:
        # Nothing nameable in it; fall back to the distinctive words.
        words = re.findall(r"[a-z]{4,}", finding.evidence.lower())
        subjects = set(sorted(set(words))[:8])

    raw = f"{finding.code}|{finding.location}|{' '.join(sorted(subjects)[:8])}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


class FindingRecord(BaseModel):
    fingerprint: str
    code: str
    location: str
    evidence: str
    rectification: str
    attempts: int = 0
    waived: bool = False

    @property
    def group(self) -> FieldGroup:
        return CODE_GROUPS.get(self.code, FieldGroup.REQUIREMENTS)

    def next_resolution(self) -> Resolution:
        """Try the fitting route first, the other one second."""
        fits_edit = self.code in EDITABLE_CODES
        if self.attempts == 0:
            return Resolution.EDIT if fits_edit else Resolution.ASK
        return Resolution.ASK if fits_edit else Resolution.EDIT

    def as_instruction(self) -> str:
        return f"[{self.code}] {self.location}: {self.evidence} -> {self.rectification}"


MAX_PRESSURE = 4  # Rounds one part of the spec may keep complaining before we stop.

# Findings that may never be waived, however many rounds they survive.
#
# The ladder exists to escape a judge's unbounded opinions, not to bypass facts.
# A live interview waived "the install command is set to the word 'install'" and
# produced a verify.sh whose first step runs a word that is not a command. No
# amount of attempts makes that acceptable: these are structural, checkable, and
# fatal, so they block until they are actually fixed.
NEVER_WAIVABLE = {
    "OPEN_QUESTION",
    "PLACEHOLDER",
    "NO_REQUIREMENTS",
    "NO_ACCEPTANCE_CRITERIA",
    "UNVERIFIABLE_CRITERION",
    "DUPLICATE_REQUIREMENT_ID",
    "DANGLING_DEPENDENCY",
    "SELF_DEPENDENCY",
    "NO_COMPONENTS",
    "COMPONENT_WITHOUT_PATHS",
    "NO_SUCCESS_CRITERIA",
    "MISSING_VERIFICATION_COMMAND",
    "EMPTY_VERIFICATION_COMMAND",
    "LABEL_AS_COMMAND",
    "MISMATCHED_TOOLCHAIN",
    "INCOMPLETE_STACK",
    "STACK_NOT_RESEARCHED",
}


class FindingLedger(BaseModel):
    """Every finding this interview has seen, and what was tried."""

    records: dict[str, FindingRecord] = Field(default_factory=dict)
    pressure: dict[str, int] = Field(default_factory=dict)

    def observe(self, report: LintReport | None) -> list[FindingRecord]:
        """Record this round's blocking findings and return the live ones.

        A finding absent from the report is dropped: it was fixed, and it should
        not count against anything if it ever reappears differently.
        """
        if report is None:
            return []

        seen: set[str] = set()
        for finding in report.errors:
            key = fingerprint(finding)
            seen.add(key)

            # A judge that rewords its complaint produces a new fingerprint every
            # round, so per-finding attempts never accumulate and the interview
            # never converges. Pressure counts how many rounds one code at one
            # location has kept objecting, whatever words it used.
            spot = f"{finding.code}|{finding.location}"
            self.pressure[spot] = self.pressure.get(spot, 0) + 1
            record = self.records.get(key)
            if record is None:
                self.records[key] = FindingRecord(
                    fingerprint=key,
                    code=finding.code,
                    location=finding.location,
                    evidence=finding.evidence,
                    rectification=finding.rectification,
                )
            else:
                record.evidence = finding.evidence
                record.rectification = finding.rectification

        for key in list(self.records):
            if key not in seen and not self.records[key].waived:
                del self.records[key]

        return [r for r in self.records.values() if not r.waived]

    def attempt(self, record: FindingRecord) -> Resolution:
        """Note that we are about to try something, and say what."""
        resolution = record.next_resolution()
        record.attempts += 1
        if record.attempts > MAX_ATTEMPTS and record.code not in NEVER_WAIVABLE:
            record.waived = True
        return resolution

    def under_pressure(self, record: FindingRecord) -> bool:
        return self.pressure.get(f"{record.code}|{record.location}", 0) >= MAX_PRESSURE

    def waive_exhausted(self) -> list[FindingRecord]:
        """Waive anything that has had its attempts, or that will not stop.

        Two exits, because there are two ways to fail to converge: one finding
        that resists fixing, and one part of the spec a judge keeps objecting to
        in freshly worded ways. Both end here rather than in an endless loop.
        """
        newly: list[FindingRecord] = []
        for record in self.records.values():
            if record.waived:
                continue
            if record.code in NEVER_WAIVABLE:
                continue
            if record.attempts >= MAX_ATTEMPTS or (
                record.attempts >= 1 and self.under_pressure(record)
            ):
                record.waived = True
                newly.append(record)
        return newly

    @property
    def open_records(self) -> list[FindingRecord]:
        return [r for r in self.records.values() if not r.waived]

    @property
    def waivers(self) -> list[FindingRecord]:
        return [r for r in self.records.values() if r.waived]

    def waiver_notes(self) -> list[str]:
        """Waivers phrased for the developer and for the generated spec."""
        notes: dict[str, str] = {}
        for record in self.waivers:
            # One line per place: a judge rewords the same objection every round,
            # and five near-identical notices read as five separate problems.
            notes[f"{record.code}|{record.location}"] = (
                f"Accepted without resolution after {record.attempts} attempts — "
                f"{record.code} at {record.location}: {record.evidence}"
            )
        return list(notes.values())

    def downgrade(self, report: LintReport | None) -> LintReport | None:
        """Turn waived findings into warnings so they stop blocking generation."""
        if report is None:
            return None
        waived = {r.fingerprint for r in self.waivers}

        def spent(finding: LintFinding) -> bool:
            """Has this objection had its turn?

            By exact identity, or by place. Matching only fingerprints left the
            interview stuck: pressure waives the record we saw, the judge then
            rewords the same complaint into a fresh fingerprint, and the new one
            blocks exactly as the old one did. A place that has objected
            MAX_PRESSURE times has been heard, whatever words it used this time.
            """
            if finding.code in NEVER_WAIVABLE:
                return False
            if fingerprint(finding) in waived:
                return True
            return self.pressure.get(f"{finding.code}|{finding.location}", 0) >= MAX_PRESSURE

        findings = [
            f.model_copy(update={"severity": Severity.WARNING})
            if f.severity is Severity.ERROR and spent(f)
            else f
            for f in report.findings
        ]
        return LintReport(findings=findings)
