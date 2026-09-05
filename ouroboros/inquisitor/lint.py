"""The ambiguity lint — the product's one hard quality gate (spec decision D6).

Ouroboros refuses to generate a harness repo while the spec is ambiguous. With
commit-time drift detection deferred to v2, this lint is the only thing standing
between a user and a plausible-looking harness built on a guessed spec, so it
errs toward refusing.

Findings deliberately reuse the evidence + rectification shape of the Inspector's
verdict schema (D18): every finding must point at something concrete and say how
to fix it. A finding without a rectification is an opinion, and opinions do not
block generation.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel

from ouroboros.models.spec import ProjectSpec

# Words that promise a quality without saying how it would ever be checked.
# A requirement built on one of these produces an acceptance check nobody can write.
VAGUE_TERMS = {
    "fast", "slow", "quick", "performant", "scalable", "robust", "reliable",
    "secure", "clean", "simple", "intuitive", "user-friendly", "seamless",
    "modern", "efficient", "flexible", "appropriate", "reasonable", "proper",
    "good", "better", "best", "nice", "smooth", "lightweight", "optimal",
}

# Markers that mean a field was left unfinished.
#
# Angle brackets alone are NOT a placeholder: a real spec said search output must
# look like "<file_path>:<line_number>: <snippet>", and a blanket <...> rule
# refused that perfectly good requirement. Only bracketed words that read as an
# instruction to the author count.
PLACEHOLDER_PATTERN = re.compile(
    r"\b(TBD|TODO|FIXME|XXX|to be (decided|determined|confirmed)|placeholder)\b"
    r"|\?{3,}"
    r"|<(your|my|insert|fill|add|choose|pick|replace|todo|tbd|placeholder)\b[^>]*>",
    re.IGNORECASE,
)

# A number, percentage, duration, or comparison rescues an otherwise vague word.
QUANTIFIER_PATTERN = re.compile(
    r"\d|\b(exactly|at (most|least)|no more than|within|under|over|equals?)\b",
    re.IGNORECASE,
)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class LintFinding(BaseModel):
    """One reason the spec is not yet safe to generate from."""

    code: str
    severity: Severity
    location: str
    evidence: str
    rectification: str


class LintReport(BaseModel):
    findings: list[LintFinding] = []

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def passed(self) -> bool:
        """True when generation may proceed."""
        return not self.errors

    def summary(self) -> str:
        if self.passed:
            note = f" ({len(self.warnings)} warnings)" if self.warnings else ""
            return f"PASS — spec is unambiguous{note}"
        return f"REFUSE — {len(self.errors)} blocking findings, {len(self.warnings)} warnings"


def _vague_words(text: str) -> list[str]:
    """Vague terms in `text` that no nearby number or bound rescues."""
    if QUANTIFIER_PATTERN.search(text):
        return []
    words = re.findall(r"[a-zA-Z][a-zA-Z-]*", text.lower())
    return sorted({w for w in words if w in VAGUE_TERMS})


def _check_open_questions(spec: ProjectSpec) -> list[LintFinding]:
    return [
        LintFinding(
            code="OPEN_QUESTION",
            severity=Severity.ERROR,
            location=f"open_questions[{i}]",
            evidence=q,
            rectification="Answer this in the interview, then fold the answer into the "
            "relevant requirement or constraint and clear the question.",
        )
        for i, q in enumerate(spec.open_questions)
    ]


def _check_placeholders(spec: ProjectSpec) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for path, text in _text_fields(spec):
        match = PLACEHOLDER_PATTERN.search(text)
        if match:
            findings.append(
                LintFinding(
                    code="PLACEHOLDER",
                    severity=Severity.ERROR,
                    location=path,
                    evidence=f"...{match.group(0)}... in: {text[:120]}",
                    rectification="Replace the placeholder with the real value. If it is "
                    "not yet known, it is an open question, not a spec field.",
                )
            )
    return findings


def _check_requirements(spec: ProjectSpec) -> list[LintFinding]:
    findings: list[LintFinding] = []

    if not spec.requirements:
        findings.append(
            LintFinding(
                code="NO_REQUIREMENTS",
                severity=Severity.ERROR,
                location="requirements",
                evidence="The spec contains zero requirements.",
                rectification="Interview the user until the system's behaviour is captured "
                "as discrete requirements with acceptance criteria.",
            )
        )
        return findings

    seen: set[str] = set()
    known = spec.requirement_ids()

    for req in spec.requirements:
        loc = f"requirements[{req.id}]"

        if req.id in seen:
            findings.append(
                LintFinding(
                    code="DUPLICATE_REQUIREMENT_ID",
                    severity=Severity.ERROR,
                    location=loc,
                    evidence=f"Requirement id '{req.id}' is used more than once.",
                    rectification="Give each requirement a unique id; task ordering and "
                    "dependency resolution key off it.",
                )
            )
        seen.add(req.id)

        if not req.acceptance_criteria:
            findings.append(
                LintFinding(
                    code="NO_ACCEPTANCE_CRITERIA",
                    severity=Severity.ERROR,
                    location=loc,
                    evidence=req.statement,
                    rectification="Add at least one observable criterion. Every checks/ "
                    "script is generated from these, so a requirement without one cannot "
                    "be verified and must not be generated.",
                )
            )

        for i, criterion in enumerate(req.acceptance_criteria):
            vague = _vague_words(criterion)
            if vague:
                findings.append(
                    LintFinding(
                        code="UNVERIFIABLE_CRITERION",
                        severity=Severity.ERROR,
                        location=f"{loc}.acceptance_criteria[{i}]",
                        evidence=f"'{criterion}' relies on: {', '.join(vague)}",
                        rectification="State the criterion as something a script can "
                        "observe — a threshold, an exact output, a status code, a file "
                        "that exists. Replace the subjective word with a measurement.",
                    )
                )

        for dep in req.depends_on:
            if dep not in known:
                findings.append(
                    LintFinding(
                        code="DANGLING_DEPENDENCY",
                        severity=Severity.ERROR,
                        location=f"{loc}.depends_on",
                        evidence=f"'{req.id}' depends on unknown requirement '{dep}'.",
                        rectification="Point the dependency at a real requirement id, or "
                        "remove it. The backlog is ordered from this graph.",
                    )
                )
            if dep == req.id:
                findings.append(
                    LintFinding(
                        code="SELF_DEPENDENCY",
                        severity=Severity.ERROR,
                        location=f"{loc}.depends_on",
                        evidence=f"'{req.id}' depends on itself.",
                        rectification="Remove the self-reference; it makes the backlog "
                        "unorderable.",
                    )
                )

    return findings


def _check_verification(spec: ProjectSpec) -> list[LintFinding]:
    """The agent's whole feedback loop is these commands. They must be real.

    Checked against the raw fields, not `commands()`. That helper filters empty
    values so `verify.sh` never renders a blank step — which meant a spec whose
    install and test were both empty strings produced an empty command list and
    sailed through this check. A live interview did exactly that: every required
    field was "present", and the generated verify.sh would have had no steps at
    all, leaving the agent with a feedback loop that always passes.
    """
    findings: list[LintFinding] = []

    for label in ("install", "test"):
        command = (getattr(spec.verification, label) or "").strip()
        if len(command) < 2:
            findings.append(
                LintFinding(
                    code="MISSING_VERIFICATION_COMMAND",
                    severity=Severity.ERROR,
                    location=f"verification.{label}",
                    evidence=f"'{label}' is empty.",
                    rectification=f"Provide the real {label} command for this stack. "
                    "verify.sh is built from these, and without them the agent has "
                    "nothing to check its work against.",
                )
            )

    for label in ("lint", "typecheck", "build", "smoke"):
        command = getattr(spec.verification, label)
        if command is not None and 0 < len(command.strip()) < 2:
            findings.append(
                LintFinding(
                    code="EMPTY_VERIFICATION_COMMAND",
                    severity=Severity.ERROR,
                    location=f"verification.{label}",
                    evidence=f"'{label}' is set to '{command}'.",
                    rectification="Provide the real command for this stack, or leave the "
                    "field unset. verify.sh runs these verbatim.",
                )
            )

    if not spec.verification.smoke:
        findings.append(
            LintFinding(
                code="NO_SMOKE_CHECK",
                severity=Severity.WARNING,
                location="verification.smoke",
                evidence="No smoke command defined.",
                rectification="Add the cheapest command proving the app starts. Without "
                "it the agent can pass tests while shipping something that never runs.",
            )
        )
    return findings


def _check_components(spec: ProjectSpec) -> list[LintFinding]:
    """Component paths become per-task scope fences, so they cannot be empty."""
    findings: list[LintFinding] = []

    if not spec.components:
        findings.append(
            LintFinding(
                code="NO_COMPONENTS",
                severity=Severity.ERROR,
                location="components",
                evidence="The spec defines no components.",
                rectification="Decompose the system into named components with owned "
                "paths; the runner's scope fence is built from them.",
            )
        )
        return findings

    for comp in spec.components:
        if not comp.paths:
            findings.append(
                LintFinding(
                    code="COMPONENT_WITHOUT_PATHS",
                    severity=Severity.ERROR,
                    location=f"components[{comp.name}].paths",
                    evidence=f"Component '{comp.name}' owns no paths.",
                    rectification="List the files or directories this component owns. "
                    "Tasks without a scope fence let the agent edit anything.",
                )
            )
    return findings


def _check_stack_coverage(spec: ProjectSpec) -> list[LintFinding]:
    if spec.stack.corpus_covered:
        return []
    return [
        LintFinding(
            code="STACK_NOT_RESEARCHED",
            severity=Severity.ERROR,
            location="stack",
            evidence=f"No corpus coverage for {spec.stack.language} / "
            f"{spec.stack.framework or 'no framework'}.",
            rectification="Run gap research for this stack and write the findings back "
            "into the corpus before generating. Generating from an unresearched stack "
            "means guessing its verification commands.",
        )
    ]


def _check_goal_framing(spec: ProjectSpec) -> list[LintFinding]:
    findings: list[LintFinding] = []
    if not spec.success_criteria:
        findings.append(
            LintFinding(
                code="NO_SUCCESS_CRITERIA",
                severity=Severity.ERROR,
                location="success_criteria",
                evidence="The spec does not say what success looks like.",
                rectification="Capture how the user will know the finished project "
                "worked. Without it, 'done' is undefined.",
            )
        )
    if not spec.non_goals:
        findings.append(
            LintFinding(
                code="NO_NON_GOALS",
                severity=Severity.WARNING,
                location="non_goals",
                evidence="No non-goals recorded.",
                rectification="Ask what the project explicitly should not do. Non-goals "
                "are the cheapest defence against agent scope creep.",
            )
        )
    return findings


def _text_fields(spec: ProjectSpec) -> list[tuple[str, str]]:
    """Every free-text field, paired with a JSON-ish path, for scanning."""
    fields: list[tuple[str, str]] = [
        ("name", spec.name),
        ("one_line", spec.one_line),
        ("problem", spec.problem),
    ]
    fields += [(f"success_criteria[{i}]", s) for i, s in enumerate(spec.success_criteria)]
    fields += [(f"non_goals[{i}]", s) for i, s in enumerate(spec.non_goals)]
    for req in spec.requirements:
        fields.append((f"requirements[{req.id}].statement", req.statement))
        fields += [
            (f"requirements[{req.id}].acceptance_criteria[{i}]", c)
            for i, c in enumerate(req.acceptance_criteria)
        ]
    for comp in spec.components:
        fields.append((f"components[{comp.name}].responsibility", comp.responsibility))
    for label, command in spec.verification.commands():
        fields.append((f"verification.{label}", command))
    return fields


CHECKS = (
    _check_open_questions,
    _check_placeholders,
    _check_goal_framing,
    _check_requirements,
    _check_verification,
    _check_components,
    _check_stack_coverage,
)


def lint_spec(spec: ProjectSpec) -> LintReport:
    """Run every deterministic ambiguity check against a spec.

    Semantic checks that need judgement — contradictions between requirements,
    domain terms used but never defined — run as a separate LLM stage and append
    to this report. Deterministic checks run first because they are free and
    their findings are not arguable.
    """
    findings: list[LintFinding] = []
    for check in CHECKS:
        findings.extend(check(spec))
    return LintReport(findings=findings)
