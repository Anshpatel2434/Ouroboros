"use client";

import { useState } from "react";
import { api } from "@/lib/api";

interface Props {
  threadId: string;
  defaultRepoName: string;
  accepted: boolean;
}

export default function PublishPanel({
  threadId,
  defaultRepoName,
  accepted,
}: Props) {
  const [token, setToken] = useState("");
  const [repoName, setRepoName] = useState(defaultRepoName);
  const [isPrivate, setPrivate] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ repo_url: string; created: boolean } | null>(
    null,
  );

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      const published = await api.publish(threadId, token, repoName, isPrivate);
      setResult(published);
      setToken(""); // Do not keep the token in memory after it is used.
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Publish failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="card__label">Ship it</div>

      <div className="btn--row" style={{ marginBottom: 16 }}>
        <a className="btn btn--ghost" href={api.downloadUrl(threadId)}>
          Download as zip
        </a>
        <span className="hint" style={{ margin: 0 }}>
          No token needed — push it yourself.
        </span>
      </div>

      {result ? (
        <div className="verdict verdict--pass">
          {result.created ? "Repository created" : "Pushed to existing repository"} —{" "}
          <a href={result.repo_url} target="_blank" rel="noreferrer">
            {result.repo_url}
          </a>
        </div>
      ) : (
        <>
          <div className="stack stack--tight">
            <div>
              <label htmlFor="repo">Repository name</label>
              <input
                id="repo"
                type="text"
                value={repoName}
                onChange={(event) => setRepoName(event.target.value)}
              />
            </div>

            <div>
              <label htmlFor="token">GitHub fine-grained token</label>
              <input
                id="token"
                type="password"
                value={token}
                placeholder="github_pat_…"
                autoComplete="off"
                onChange={(event) => setToken(event.target.value)}
              />
              <p className="hint">
                Needs <strong>Contents: read and write</strong> plus{" "}
                <strong>Administration: read and write</strong> to create the repo.
                Used once for the push and never stored — not on disk, and not in
                the repo&apos;s git config.
              </p>
            </div>

            <label
              style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 400 }}
            >
              <input
                type="checkbox"
                checked={isPrivate}
                onChange={(event) => setPrivate(event.target.checked)}
              />
              Create as a private repository
            </label>
          </div>

          {error ? (
            <div className="banner" style={{ marginTop: 12 }}>
              {error}
            </div>
          ) : null}

          {!accepted ? (
            <p className="hint">
              Publishing is blocked while the self-review has blocking findings.
            </p>
          ) : null}

          <div className="btn--row" style={{ marginTop: 12 }}>
            <button
              className="btn"
              type="button"
              disabled={busy || !accepted || !token.trim() || !repoName.trim()}
              onClick={publish}
            >
              {busy ? <span className="spinner" /> : null}
              {busy ? "Pushing" : "Create repo and push"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
