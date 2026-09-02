"""The judgement half of the ambiguity lint.

Deterministic checks catch what is mechanically wrong (missing fields, vague
words, dangling ids). They cannot catch two requirements that quietly
contradict each other, or a term everyone in the room understood and nobody
wrote down. That is this module.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ouroboros.inquisitor.lint import LintFinding, LintReport, Severity
from ouroboros.inquisitor.prompts import SEMANTIC_LINT
from ouroboros.llm.client import LLM
from ouroboros.models.spec import ProjectSpec


class SemanticFinding(BaseModel):
    code: str = Field(description="CONTRADICTION | UNDEFINED_TERM | UNBUILDABLE_CRITERION | COVERAGE_HOLE")
    severity: str = Field(description="error or warning")
    location: str
    evidence: str
    rectification: str


class SemanticReport(BaseModel):
    findings: list[SemanticFinding] = Field(default_factory=list)


def semantic_lint(llm: LLM, spec: ProjectSpec) -> LintReport:
    """Run the LLM checks and return them in the same shape as the hard lint."""
    result = llm.structured(
        SemanticReport,
        system=SEMANTIC_LINT,
        user="Review this specification:\n\n" + spec.model_dump_json(indent=2),
    )

    findings = [
        LintFinding(
            code=f.code.strip().upper().replace(" ", "_") or "SEMANTIC",
            severity=Severity.ERROR if f.severity.lower() == "error" else Severity.WARNING,
            location=f.location,
            evidence=f.evidence,
            rectification=f.rectification,
        )
        for f in result.findings
        # A finding with no fix is an opinion; opinions do not block generation.
        if f.evidence.strip() and f.rectification.strip()
    ]
    return LintReport(findings=findings)


def full_lint(llm: LLM | None, spec: ProjectSpec) -> LintReport:
    """Deterministic checks first (free, unarguable), then judgement.

    Semantic checks are skipped when the hard checks already refuse: there is no
    point paying a model to critique a spec we have already rejected.
    """
    from ouroboros.inquisitor.lint import lint_spec

    report = lint_spec(spec)
    if llm is None or not report.passed:
        return report

    semantic = semantic_lint(llm, spec)
    return LintReport(findings=report.findings + semantic.findings)
