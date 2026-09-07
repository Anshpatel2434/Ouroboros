"use client";

import { useEffect, useState } from "react";
import type { Question } from "@/lib/api";

interface Props {
  questions: Question[];
  rationale: string;
  round: number;
  busy: boolean;
  onSubmit: (answers: { question_id: string; value: string }[]) => void;
}

export default function Questions({
  questions,
  rationale,
  round,
  busy,
  onSubmit,
}: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [multi, setMulti] = useState<Record<string, string[]>>({});
  // Free text for "Something else", kept separate so choosing it clears any
  // option the developer had picked before changing their mind.
  const [other, setOther] = useState<Record<string, string>>({});

  // A new round is a new set of questions; never carry answers across.
  useEffect(() => {
    setValues({});
    setMulti({});
    setOther({});
  }, [questions]);

  const answerFor = (question: Question): string => {
    const written = (other[question.id] ?? "").trim();

    // On a multi-select, "Something else" adds to the chosen options rather
    // than replacing them. Replacing meant a developer who ticked install,
    // test and lint and then added a note silently lost all three.
    if (question.kind === "multi_select") {
      const picked = multi[question.id] ?? [];
      return [...picked, ...(written ? [written] : [])].join(", ");
    }

    return other[question.id] !== undefined ? written : (values[question.id] ?? "");
  };

  const complete = questions.every((q) => answerFor(q).trim().length > 0);

  const toggle = (question: Question, label: string) => {
    setMulti((previous) => {
      const current = previous[question.id] ?? [];
      return {
        ...previous,
        [question.id]: current.includes(label)
          ? current.filter((item) => item !== label)
          : [...current, label],
      };
    });
  };

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(
          questions.map((question) => ({
            question_id: question.id,
            value: answerFor(question),
          })),
        );
      }}
    >
      <div>
        <div className="card__label">Round {round}</div>
        {rationale ? <p className="hint" style={{ marginTop: 0 }}>{rationale}</p> : null}
      </div>

      {questions.map((question) => (
        <div className="question" key={question.id}>
          <span className="chip">{question.header}</span>
          <p className="question__text">{question.text}</p>
          <p className="question__why">{question.why_it_matters}</p>

          {/* Options decide the control, not `kind`. A model that supplies three
              choices while leaving kind as "text" is common, and keying off kind
              first hid real options behind a text box — the developer typed an
              answer to something they should have clicked. */}
          {question.options.length === 0 ? (
            <textarea
              rows={3}
              value={values[question.id] ?? ""}
              placeholder="Your answer"
              onChange={(event) =>
                setValues((previous) => ({
                  ...previous,
                  [question.id]: event.target.value,
                }))
              }
            />
          ) : (
            <div>
              {question.options.map((option) => {
                const selected =
                  question.kind === "multi_select"
                    ? (multi[question.id] ?? []).includes(option.label)
                    : values[question.id] === option.label;

                return (
                  <label
                    key={option.label}
                    className={`option${selected ? " option--selected" : ""}`}
                  >
                    <input
                      type={question.kind === "multi_select" ? "checkbox" : "radio"}
                      name={question.id}
                      checked={selected}
                      onChange={() =>
                        question.kind === "multi_select"
                          ? toggle(question, option.label)
                          : setValues((previous) => ({
                              ...previous,
                              [question.id]: option.label,
                            }))
                      }
                    />
                    <span>
                      <span className="option__label">{option.label}</span>
                      {option.description ? (
                        <>
                          <br />
                          <span className="option__description">
                            {option.description}
                          </span>
                        </>
                      ) : null}
                    </span>
                  </label>
                );
              })}

              {/* None of the options may fit, and a developer with no way to say
                  so either abandons the interview or picks something untrue —
                  which then becomes a requirement nobody wanted. */}
              <label
                className={`option${
                  other[question.id] !== undefined ? " option--selected" : ""
                }`}
              >
                <input
                  type={question.kind === "multi_select" ? "checkbox" : "radio"}
                  name={question.id}
                  checked={other[question.id] !== undefined}
                  onChange={() =>
                    setOther((previous) => {
                      const next = { ...previous };
                      if (question.id in next) {
                        delete next[question.id];
                      } else {
                        next[question.id] = "";
                      }
                      return next;
                    })
                  }
                />
                <span className="option__label">Something else</span>
              </label>

              {other[question.id] !== undefined ? (
                <textarea
                  rows={2}
                  style={{ marginTop: 8 }}
                  value={other[question.id]}
                  placeholder="In your own words"
                  onChange={(event) =>
                    setOther((previous) => ({
                      ...previous,
                      [question.id]: event.target.value,
                    }))
                  }
                />
              ) : null}
            </div>
          )}
        </div>
      ))}

      <div className="btn--row">
        <button className="btn" type="submit" disabled={busy || !complete}>
          {busy ? <span className="spinner" /> : null}
          {busy ? "Thinking" : "Submit answers"}
        </button>
        {!complete ? (
          <span className="hint" style={{ margin: 0 }}>
            Answer every question — a skipped answer becomes a guess later.
          </span>
        ) : null}
      </div>
    </form>
  );
}
