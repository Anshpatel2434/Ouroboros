---
title: LangGraph Human-in-the-Loop — interrupt(), Command(resume), Breakpoints
source_url: https://docs.langchain.com/oss/python/langgraph/interrupts
publisher: LangChain
retrieved: 2026-08-25
domain: orchestration-langgraph
doc_type: official-docs
relevance: The Inquisitor's entire ask-question/wait-for-founder loop and the Inspector's approval gates are built on interrupt/resume.
---

## Summary

LangGraph pauses a running graph indefinitely with the `interrupt()` function
called inside a node; the payload surfaces to the caller, and execution resumes
later — on the same thread — by invoking the graph with `Command(resume=value)`,
whose value becomes the return value of the original `interrupt()` call. This
requires a checkpointer and a `thread_id`. The critical gotcha is that on resume
the whole node re-runs from its beginning, so code before the interrupt must be
idempotent. Static breakpoints (`interrupt_before`/`interrupt_after`) are a
separate compile-time mechanism aimed at debugging.

## Key knowledge

- Dynamic interrupt:
  ```python
  from langgraph.types import interrupt

  def node_function(state: State):
      result = interrupt("payload")   # any JSON-serializable value
      return {"key": result}
  ```
  `interrupt(payload)` pauses at the call site; the payload is surfaced to the caller. The value later passed in `Command(resume=...)` becomes `interrupt()`'s return value.
- Resume:
  ```python
  from langgraph.types import Command
  graph.invoke(Command(resume=value), config=config)          # classic
  graph.stream_events(Command(resume=value), config=config, version="v3")
  ```
- Prerequisites: graph compiled with a checkpointer (`builder.compile(checkpointer=InMemorySaver())`) and invoked with `{"configurable": {"thread_id": "..."}}`. Resume must use the same thread_id.
- Detecting the pause:
  - Default `graph.invoke()` surfaces interrupts under `result["__interrupt__"]`.
  - `stream_events(..., version="v3")` exposes `stream.interrupted` (bool), `stream.interrupts` (tuple of `Interrupt` objects with payloads and ids), `stream.output`, `stream.messages`.
  - v2 `invoke()` returns a `GraphOutput` with `.value` and `.interrupts` instead of the embedded `__interrupt__` key.
- Multiple concurrent interrupts (parallel nodes paused at once): resume all with a map keyed by interrupt id:
  ```python
  resume_map = {i.id: response for i in stream.interrupts}
  graph.invoke(Command(resume=resume_map), config=config)
  ```
- Gotchas:
  - On resume the node restarts from its beginning — everything before the `interrupt()` call runs again. Side effects before an interrupt must be idempotent; prefer placing side effects after the interrupt.
  - Never wrap `interrupt()` in a bare `try/except` — it works by raising a special internal exception; catching it breaks the pause.
  - Multiple interrupts within one node must occur in a deterministic, identical order on every execution (no conditional skipping, no non-deterministic loops), or resume values will be mismatched.
  - To validate human input, loop back to the node via a conditional edge rather than looping around the interrupt inside the node.
- Common patterns:
  - Approval gate: `decision = interrupt({"question": "Approve?", "details": state["action"]})` then `return Command(goto="proceed" if decision else "cancel")`.
  - Review-and-edit: `edited = interrupt({"instruction": "Review", "content": state["text"]}); return {"text": edited}`.
  - Tool approval: call `interrupt()` inside the tool function itself so the human reviews tool args before execution.
- Static breakpoints (debugging-oriented): `graph.compile(interrupt_before=["node_a"], interrupt_after=["node_b"])`; also settable at runtime via invoke parameters. Resume past a static breakpoint by invoking with `None` as input: `graph.invoke(None, config=config)`.

## Notable quotes

> "The value passed to Command(resume=...) becomes the return value of the interrupt call." — LangChain docs

> "Side effects called before interrupt must be idempotent." — LangChain docs

## Application to Ouroboros

The Inquisitor is one long interrupt loop: each question to the founder is an
`interrupt({"question": ...})` and the founder's answer arrives via
`Command(resume=answer)` on the interview thread — which is why the Inquisitor
must ship with a durable checkpointer. The Slop Inspector uses the approval-gate
pattern before any destructive verdict action (e.g. blocking a commit or opening
an issue), and the Generator can pause for scaffold-plan sign-off with
review-and-edit before writing files. The runner must check `__interrupt__` /
`GraphOutput.interrupts` after every invoke and never wrap node bodies in blanket
try/except.
