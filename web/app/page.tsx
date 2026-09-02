"use client";

import { useState } from "react";
import GenerationPanel from "@/components/GenerationPanel";
import LintPanel from "@/components/LintPanel";
import PublishPanel from "@/components/PublishPanel";
import Questions from "@/components/Questions";
import SpecPanel from "@/components/SpecPanel";
import { api, type Generation, type Snapshot } from "@/lib/api";

const EXAMPLE =
  "A CLI that watches a folder of markdown notes and keeps a searchable index, so I can grep my second brain from anywhere.";

export default function Home() {
  const [brief, setBrief] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [generation, setGeneration] = useState<Generation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async <T,>(work: () => Promise<T>, apply: (result: T) => void) => {
    setBusy(true);
    setError(null);
    try {
      apply(await work());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const start = () => run(() => api.start(brief), setSnapshot);

  const answer = (answers: { question_id: string; value: string }[]) =>
    run(() => api.answer(snapshot!.thread_id, answers), setSnapshot);

  const generate = () =>
    run(() => api.generate(snapshot!.thread_id), setGeneration);

  const reset = () => {
    setSnapshot(null);
    setGeneration(null);
    setBrief("");
    setError(null);
  };

  const slug =
    (snapshot?.spec?.slug as string | undefined) ??
    (snapshot?.draft?.slug as string | undefined) ??
    "harness-repo";

  return (
    <div className="shell">
      <header className="masthead">
        <span className="wordmark">Ouroboros</span>
        <p>
          Interviews you until the spec is unambiguous, then generates the harness
          repo your coding agent works inside.
        </p>
        {snapshot ? (
          <button className="btn btn--ghost spacer" type="button" onClick={reset}>
            New project
          </button>
        ) : null}
      </header>

      <div className="columns">
        <main className="column">
          <div className="stack">
            {error ? <div className="banner">{error}</div> : null}

            {!snapshot ? (
              <div className="card">
                <h1 className="card__title">What are you building?</h1>
                <p className="hint" style={{ marginTop: 0, marginBottom: 14 }}>
                  A paragraph is plenty. Everything vague in it becomes a question,
                  and nothing gets generated until none are left.
                </p>
                <textarea
                  rows={5}
                  value={brief}
                  placeholder={EXAMPLE}
                  onChange={(event) => setBrief(event.target.value)}
                />
                <div className="btn--row" style={{ marginTop: 12 }}>
                  <button
                    className="btn"
                    type="button"
                    onClick={start}
                    disabled={busy || brief.trim().length < 12}
                  >
                    {busy ? <span className="spinner" /> : null}
                    {busy ? "Opening the interview" : "Begin interview"}
                  </button>
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => setBrief(EXAMPLE)}
                    disabled={busy}
                  >
                    Use the example
                  </button>
                </div>
              </div>
            ) : null}

            {snapshot?.status === "interviewing" && snapshot.questions.length > 0 ? (
              <div className="card">
                <Questions
                  questions={snapshot.questions}
                  rationale={snapshot.rationale}
                  round={snapshot.round}
                  busy={busy}
                  onSubmit={answer}
                />
              </div>
            ) : null}

            {snapshot?.status === "ready" && !generation ? (
              <div className="card">
                <h2 className="card__title">The spec holds up</h2>
                <p className="hint" style={{ marginTop: 0 }}>
                  Every required field is filled, every acceptance criterion is
                  checkable, and nothing contradicts. Generation will produce the
                  harness layer, a runnable project skeleton, and the runner.
                </p>
                <div className="btn--row" style={{ marginTop: 12 }}>
                  <button
                    className="btn"
                    type="button"
                    onClick={generate}
                    disabled={busy}
                  >
                    {busy ? <span className="spinner" /> : null}
                    {busy ? "Generating and reviewing" : "Generate the repo"}
                  </button>
                </div>
              </div>
            ) : null}

            {snapshot?.status === "exhausted" ? (
              <div className="card">
                <h2 className="card__title">Stopped without a clean spec</h2>
                <p className="hint" style={{ marginTop: 0 }}>
                  The interview hit its round limit with findings outstanding.
                  Generation stays refused — a harness built on this spec would be
                  guesswork. The findings alongside say exactly what is missing.
                </p>
              </div>
            ) : null}

            {generation ? (
              <>
                <GenerationPanel
                  threadId={snapshot!.thread_id}
                  generation={generation}
                />
                <PublishPanel
                  threadId={snapshot!.thread_id}
                  defaultRepoName={slug}
                  accepted={generation.accepted}
                />
              </>
            ) : null}
          </div>
        </main>

        <aside className="column column--aside">
          {snapshot ? (
            <div className="stack">
              <LintPanel snapshot={snapshot} />
              <SpecPanel snapshot={snapshot} />
            </div>
          ) : (
            <div className="stack">
              <div className="card">
                <div className="card__label">How this works</div>
                <ol style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
                  <li>You describe the project.</li>
                  <li>
                    The Inquisitor asks two or three questions at a time until
                    nothing is ambiguous.
                  </li>
                  <li>
                    The ambiguity lint refuses to generate while anything is
                    unverifiable, contradictory, or missing.
                  </li>
                  <li>
                    Generation emits the guardrails, a skeleton whose tests already
                    pass, and the runner that drives your agent.
                  </li>
                  <li>Push it to GitHub, or take the zip.</li>
                </ol>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
