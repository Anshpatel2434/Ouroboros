"""The finding ledger — why the interview now terminates.

Before this existed, each round re-linted, got the same complaint, turned it
into another question, and started over. A live interview spent four rounds on
"R-009 is redundant with R-006, remove it" because the only move the
architecture had was to ask the developer something, and no answer deletes a
requirement.
"""

from __future__ import annotations

from ouroboros.inquisitor.findings import (
    MAX_ATTEMPTS,
    FindingLedger,
    Resolution,
    fingerprint,
)
from ouroboros.inquisitor.lint import LintFinding, LintReport, Severity
from ouroboros.models.patches import FieldGroup


def finding(code="CONTRADICTION", location="requirements", evidence="R-009 duplicates R-006.") -> LintFinding:
    return LintFinding(
        code=code,
        severity=Severity.ERROR,
        location=location,
        evidence=evidence,
        rectification="Remove R-009.",
    )


def report(*findings) -> LintReport:
    return LintReport(findings=list(findings))


def test_the_same_complaint_reworded_is_the_same_finding():
    """Judges reword every time. Without normalisation nothing ever escalates."""
    a = finding(evidence="R-009 duplicates R-006 and adds nothing.")
    b = finding(evidence="Requirement R-009 is redundant: it duplicates R-006.")
    assert fingerprint(a) == fingerprint(b)


def test_a_different_complaint_is_a_different_finding():
    assert fingerprint(finding()) != fingerprint(
        finding(code="COVERAGE_HOLE", evidence="Nothing delivers R-004.")
    )


def test_a_finding_cannot_survive_more_rounds_than_the_ladder_allows():
    """The termination proof: every finding is resolved or waived, never endless."""
    ledger = FindingLedger()
    for _ in range(MAX_ATTEMPTS + 2):
        live = ledger.observe(report(finding()))
        for record in live:
            ledger.attempt(record)
        ledger.waive_exhausted()

    assert ledger.open_records == []
    assert len(ledger.waivers) == 1


def test_escalation_tries_the_other_route_second():
    """An editable finding is edited first, then asked about if the edit failed."""
    ledger = FindingLedger()

    live = ledger.observe(report(finding()))
    assert ledger.attempt(live[0]) is Resolution.EDIT

    live = ledger.observe(report(finding()))
    assert ledger.attempt(live[0]) is Resolution.ASK


def test_a_finding_only_the_developer_can_answer_is_asked_first():
    ledger = FindingLedger()
    live = ledger.observe(report(finding(code="COVERAGE_HOLE")))
    assert ledger.attempt(live[0]) is Resolution.ASK


def test_a_resolved_finding_is_forgotten():
    ledger = FindingLedger()
    ledger.observe(report(finding()))
    assert ledger.open_records

    ledger.observe(report())
    assert ledger.open_records == []


def test_findings_are_routed_to_the_part_of_the_spec_they_live_in():
    ledger = FindingLedger()
    live = ledger.observe(
        report(
            finding(code="UNDEFINED_TERM", location="glossary", evidence="'hit' is undefined."),
            finding(code="COMPONENT_WITHOUT_PATHS", location="components", evidence="No paths."),
        )
    )
    groups = {r.code: r.group for r in live}

    assert groups["UNDEFINED_TERM"] is FieldGroup.GLOSSARY
    assert groups["COMPONENT_WITHOUT_PATHS"] is FieldGroup.COMPONENTS


def test_waived_findings_stop_blocking_but_stay_visible():
    """A waiver is an accepted assumption, not a silent pass."""
    ledger = FindingLedger()
    live = ledger.observe(report(finding()))
    for _ in range(MAX_ATTEMPTS):
        ledger.attempt(live[0])
    ledger.waive_exhausted()

    downgraded = ledger.downgrade(report(finding()))
    assert downgraded.passed, "a waived finding must not keep blocking generation"
    assert downgraded.warnings, "but it must still be reported"
    assert ledger.waiver_notes()
    assert "R-009" in ledger.waiver_notes()[0]


def test_unwaived_findings_still_block():
    ledger = FindingLedger()
    ledger.observe(report(finding()))
    downgraded = ledger.downgrade(report(finding()))
    assert not downgraded.passed


def test_a_reworded_complaint_still_converges():
    """The judge invents new wording each round, so fingerprints keep changing.

    A live interview stalled exactly here: ten rounds, one blocking finding, a
    different fingerprint every time, so per-finding attempts never accumulated.
    Pressure counts objections per code and location, whatever words are used.
    """
    from ouroboros.inquisitor.findings import MAX_PRESSURE

    ledger = FindingLedger()
    for round_no in range(MAX_PRESSURE + 1):
        live = ledger.observe(
            report(finding(evidence=f"Wording number {round_no} about R-00{round_no}."))
        )
        for record in live:
            ledger.attempt(record)
        ledger.waive_exhausted()

    assert ledger.open_records == [], "a reworded complaint must not block forever"
    assert ledger.waivers


def test_pressure_is_tracked_per_location_not_globally():
    """One noisy part of the spec must not waive findings elsewhere."""
    ledger = FindingLedger()
    for _ in range(6):
        live = ledger.observe(
            report(
                finding(location="requirements", evidence="Noisy, reworded each time."),
            )
        )
        for record in live:
            ledger.attempt(record)
        ledger.waive_exhausted()

    fresh = ledger.observe(report(finding(code="UNDEFINED_TERM", location="glossary")))
    assert fresh, "a new finding elsewhere is still live"
    assert not ledger.under_pressure(fresh[0])


def test_a_reworded_finding_is_downgraded_by_place():
    """Waiving by fingerprint alone left the interview stuck.

    Pressure waives the record we saw; the judge then rewords the same
    complaint into a fresh fingerprint and the new one blocks exactly as the old
    one did. A live interview sat on two coverage holes for four rounds this way.
    """
    from ouroboros.inquisitor.findings import MAX_PRESSURE

    ledger = FindingLedger()
    for n in range(MAX_PRESSURE):
        live = ledger.observe(report(finding(code="COVERAGE_HOLE", evidence=f"Wording {n}.")))
        for record in live:
            ledger.attempt(record)
        ledger.waive_exhausted()

    fresh = report(finding(code="COVERAGE_HOLE", evidence="An entirely new phrasing."))
    assert ledger.downgrade(fresh).passed


def test_structural_findings_are_never_downgraded_by_pressure():
    """No amount of repetition makes a broken install command acceptable."""
    from ouroboros.inquisitor.findings import MAX_PRESSURE

    ledger = FindingLedger()
    for n in range(MAX_PRESSURE + 2):
        live = ledger.observe(
            report(finding(code="LABEL_AS_COMMAND", location="verification.install",
                           evidence=f"Still the word install, wording {n}."))
        )
        for record in live:
            ledger.attempt(record)
        ledger.waive_exhausted()

    still = report(finding(code="LABEL_AS_COMMAND", location="verification.install"))
    assert not ledger.downgrade(still).passed
