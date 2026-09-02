"use client";

import { useState } from "react";
import { api, type Generation } from "@/lib/api";

interface Props {
  threadId: string;
  generation: Generation;
}

export default function GenerationPanel({ threadId, generation }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const [contents, setContents] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const blocking = generation.review.findings.filter((f) => f.blocking);
  const advisory = generation.review.findings.filter((f) => !f.blocking);

  const preview = async (path: string) => {
    if (open === path) {
      setOpen(null);
      return;
    }
    setLoading(true);
    setOpen(path);
    try {
      const file = await api.readFile(threadId, path);
      setContents(file.contents);
    } catch (error) {
      setContents(error instanceof Error ? error.message : "Could not read file.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="stack">
      <div className="card">
        <div className="card__label">Self-review</div>
        <div
          className={`verdict verdict--${generation.accepted ? "pass" : "error"}`}
        >
          {generation.review_summary}
          {generation.attempts > 1
            ? ` · corrected and re-reviewed (${generation.attempts} attempts)`
            : null}
        </div>

        {blocking.length > 0 ? (
          <div className="stack stack--tight" style={{ marginTop: 12 }}>
            {blocking.map((finding, index) => (
              <div className="finding finding--error" key={index}>
                <div className="finding__head">
                  <span className="finding__code mono">BLOCKING</span>
                  <span className="finding__location mono">{finding.location}</span>
                </div>
                <div>{finding.issue}</div>
                <div className="finding__fix">{finding.fix}</div>
              </div>
            ))}
          </div>
        ) : null}

        {advisory.length > 0 ? (
          <details style={{ marginTop: 12 }}>
            <summary className="hint">
              {advisory.length} advisory finding{advisory.length === 1 ? "" : "s"}
            </summary>
            <div className="stack stack--tight" style={{ marginTop: 8 }}>
              {advisory.map((finding, index) => (
                <div className="finding finding--warning" key={index}>
                  <div className="finding__head">
                    <span className="finding__location mono">{finding.location}</span>
                  </div>
                  <div>{finding.issue}</div>
                  <div className="finding__fix">{finding.fix}</div>
                </div>
              ))}
            </div>
          </details>
        ) : null}

        {generation.notes.length > 0 ? (
          <ul className="pill-list" style={{ marginTop: 12 }}>
            {generation.notes.map((note) => (
              <li className="pill" key={note}>
                {note}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="card">
        <div className="card__label">
          Backlog ({generation.backlog.tasks.length} one-commit tasks)
        </div>
        <div className="scroll">
          <table className="file-table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Title</th>
                <th>Scope fence</th>
              </tr>
            </thead>
            <tbody>
              {generation.backlog.tasks.map((task) => (
                <tr key={task.id}>
                  <td className="mono">{task.id}</td>
                  <td>{task.title}</td>
                  <td className="mono" style={{ fontSize: 12 }}>
                    {task.scope_paths.join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card__label">
          Generated repository ({generation.files.length} files)
        </div>
        <div className="scroll">
          <table className="file-table">
            <tbody>
              {generation.files.map((file) => (
                <tr key={file.path}>
                  <td>
                    <button
                      className="btn btn--ghost"
                      style={{ padding: "2px 8px", fontSize: 13 }}
                      onClick={() => preview(file.path)}
                      type="button"
                    >
                      {open === file.path ? "Hide" : "View"}
                    </button>
                  </td>
                  <td className="mono">
                    {file.path}
                    {file.executable ? " *" : ""}
                  </td>
                  <td style={{ textAlign: "right", color: "var(--ink-muted)" }}>
                    {file.bytes} B
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {open ? (
          <pre className="code scroll" style={{ marginTop: 12 }}>
            {loading ? "Loading…" : contents}
          </pre>
        ) : null}

        <p className="hint">
          Written to <span className="mono">{generation.output_dir}</span>
        </p>
      </div>
    </div>
  );
}
