"use client";

import type { LintFinding, Snapshot } from "@/lib/api";

export default function LintPanel({ snapshot }: { snapshot: Snapshot }) {
  const findings: LintFinding[] = snapshot.lint?.findings ?? [];
  const errors = findings.filter((f) => f.severity === "error");
  const warnings = findings.filter((f) => f.severity === "warning");

  const state =
    snapshot.status === "ready"
      ? "pass"
      : snapshot.status === "exhausted"
        ? "error"
        : errors.length > 0
          ? "error"
          : "warn";

  const headline =
    snapshot.status === "ready"
      ? "Spec is unambiguous — generation unlocked"
      : snapshot.status === "exhausted"
        ? "Interview stopped without a clean spec"
        : errors.length > 0
          ? `Generation refused — ${errors.length} blocking finding${errors.length === 1 ? "" : "s"}`
          : "Interview in progress";

  return (
    <div className="card">
      <div className="card__label">Ambiguity lint</div>
      <div className={`verdict verdict--${state}`}>{headline}</div>

      {snapshot.notices.length > 0 ? (
        <ul className="pill-list" style={{ marginTop: 12 }}>
          {snapshot.notices.map((notice) => (
            <li className="pill" key={notice}>
              {notice}
            </li>
          ))}
        </ul>
      ) : null}

      {findings.length > 0 ? (
        <div className="stack stack--tight scroll" style={{ marginTop: 12 }}>
          {[...errors, ...warnings].map((finding, index) => (
            <div className={`finding finding--${finding.severity}`} key={index}>
              <div className="finding__head">
                <span className="finding__code mono">{finding.code}</span>
                <span className="finding__location mono">{finding.location}</span>
              </div>
              <div>{finding.evidence}</div>
              <div className="finding__fix">{finding.rectification}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className="hint">
          Findings appear here the moment the spec is complete enough to check.
        </p>
      )}
    </div>
  );
}
