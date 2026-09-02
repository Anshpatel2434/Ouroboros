"use client";

import type { Snapshot } from "@/lib/api";

const REQUIRED_FIELDS = [
  "name",
  "one_line",
  "problem",
  "stack",
  "verification",
  "success_criteria",
  "components",
  "requirements",
];

function asList(value: unknown): string[] {
  return Array.isArray(value) ? (value as string[]) : [];
}

export default function SpecPanel({ snapshot }: { snapshot: Snapshot }) {
  const draft = snapshot.draft as Record<string, any>;
  const missing = new Set(snapshot.missing_fields);
  const filled = REQUIRED_FIELDS.length - missing.size;
  const percent = Math.round((filled / REQUIRED_FIELDS.length) * 100);

  const stack = draft?.stack as Record<string, any> | null;
  const verification = draft?.verification as Record<string, any> | null;
  const requirements = Array.isArray(draft?.requirements) ? draft.requirements : [];
  const components = Array.isArray(draft?.components) ? draft.components : [];

  return (
    <div className="stack">
      <div className="card">
        <div className="card__label">Specification</div>
        <div className="stack stack--tight">
          <div className="meter" aria-hidden="true">
            <div className="meter__fill" style={{ width: `${percent}%` }} />
          </div>
          <p className="hint" style={{ margin: 0 }}>
            {filled} of {REQUIRED_FIELDS.length} required sections filled
          </p>
        </div>

        {draft?.name ? (
          <dl className="kv" style={{ marginTop: 14 }}>
            <dt>Name</dt>
            <dd>{draft.name}</dd>
            {draft.one_line ? (
              <>
                <dt>Summary</dt>
                <dd>{draft.one_line}</dd>
              </>
            ) : null}
            {stack?.language ? (
              <>
                <dt>Stack</dt>
                <dd>
                  {stack.language} {stack.language_version}
                  {stack.framework ? ` · ${stack.framework}` : ""}
                  {stack.package_manager ? ` · ${stack.package_manager}` : ""}
                </dd>
              </>
            ) : null}
            {verification?.test ? (
              <>
                <dt>Verify</dt>
                <dd className="mono">{verification.test}</dd>
              </>
            ) : null}
          </dl>
        ) : (
          <p className="empty" style={{ marginBottom: 0 }}>
            Nothing captured yet. The spec fills in as you answer.
          </p>
        )}

        {missing.size > 0 ? (
          <ul className="pill-list" style={{ marginTop: 14 }}>
            {Array.from(missing).map((field) => (
              <li className="pill" key={field}>
                {field} missing
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {requirements.length > 0 ? (
        <div className="card">
          <div className="card__label">Requirements ({requirements.length})</div>
          <div className="stack stack--tight scroll">
            {requirements.map((requirement: any) => (
              <div key={requirement.id}>
                <strong className="mono" style={{ fontSize: 12 }}>
                  {requirement.id}
                </strong>{" "}
                <span style={{ fontSize: 13 }}>{requirement.statement}</span>
                <ul className="pill-list" style={{ marginTop: 4 }}>
                  {asList(requirement.acceptance_criteria).map((criterion) => (
                    <li className="pill" key={criterion}>
                      {criterion}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {components.length > 0 ? (
        <div className="card">
          <div className="card__label">Components</div>
          <dl className="kv">
            {components.map((component: any) => (
              <div key={component.name} style={{ display: "contents" }}>
                <dt>{component.name}</dt>
                <dd className="mono" style={{ fontSize: 12 }}>
                  {asList(component.paths).join(", ") || "no paths"}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {snapshot.transcript.length > 0 ? (
        <div className="card">
          <div className="card__label">Transcript</div>
          <div className="transcript scroll">
            {snapshot.transcript.map((turn, index) => (
              <div key={index}>
                <p className="transcript__q" style={{ margin: "0 0 2px" }}>
                  {turn.question}
                </p>
                <p className="transcript__a">{turn.answer}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
