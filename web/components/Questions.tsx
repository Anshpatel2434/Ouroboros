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

  // A new round is a new set of questions; never carry answers across.
  useEffect(() => {
    setValues({});
    setMulti({});
  }, [questions]);

  const answerFor = (question: Question): string =>
    question.kind === "multi_select"
      ? (multi[question.id] ?? []).join(", ")
      : (values[question.id] ?? "");

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

          {question.kind === "text" || question.options.length === 0 ? (
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
