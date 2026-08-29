---
title: Send API — Dynamic Fan-Out and Map-Reduce over Runtime-Decided Items
source_url: https://docs.langchain.com/oss/python/langgraph/graph-api
publisher: LangChain
retrieved: 2026-08-26
domain: orchestration-langgraph
doc_type: official-docs
relevance: Lets Ouroboros graphs fan out over collections known only at runtime — files in a commit, questions in an interview plan, scaffold modules — and reduce results back into shared state.
---

## Summary

Static edges cannot express "run node W once per item in a list computed at
runtime." LangGraph's `Send` API solves this: a conditional-edge function
returns a list of `Send(node, arg)` objects, and the runtime schedules one
parallel invocation of the target node per `Send`, each receiving its own
private state dict (which may differ from the graph's state schema). Results
are merged back into shared state through reducer-annotated keys
(`Annotated[list, operator.add]`), giving a map-reduce pattern inside a single
graph step. (Constructor details corroborated against
https://reference.langchain.com/python/langgraph/types/Send.)

## Key knowledge

- Import: `from langgraph.types import Send`.
- Constructor (reference docs):
  ```python
  Send(
      self, /,
      node: str,   # "The name of the target node to send the message to."
      arg: Any,    # "The state or message to send to the target node."
      *,
      timeout: float | timedelta | TimeoutPolicy | None = None,
  )
  ```
- Fan-out mechanics: a function passed to `add_conditional_edges` returns a **list of `Send` objects** instead of a node name; the runtime invokes the target node once per `Send`, in parallel, in the next superstep:
  ```python
  def continue_to_jokes(state: OverallState):
      return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

  graph.add_conditional_edges("node_a", continue_to_jokes)
  ```
  The fan-out source can also be `START`: `builder.add_conditional_edges(START, continue_to_jokes)`.
- Private worker state: each `Send`'s `arg` dict is delivered as that invocation's entire input — "the sent state can differ from the core graph's state." Workers therefore commonly declare their own small state schema (e.g. `{"subject": str}`) rather than `OverallState`.
- Reduce step: workers write to a shared key whose reducer merges parallel results:
  ```python
  from operator import add
  from typing import Annotated
  from typing_extensions import TypedDict

  class State(TypedDict):
      results: Annotated[list[str], add]
  ```
  Each worker returns e.g. `{"results": [item]}`; the `add` reducer concatenates across all parallel branches. Without a reducer, concurrent writes to the same key raise an invalid-update error.
- End-to-end minimal example (reference docs):
  ```python
  builder = StateGraph(OverallState)
  builder.add_node("generate_joke", lambda state: {"jokes": [f"Joke about {state['subject']}"]})
  builder.add_conditional_edges(START, continue_to_jokes)
  graph = builder.compile()

  graph.invoke({"subjects": ["cats", "dogs"]})
  # {'subjects': ['cats', 'dogs'], 'jokes': ['Joke about cats', 'Joke about dogs']}
  ```
- Per-`Send` `timeout` accepts a float/`timedelta` or a full `TimeoutPolicy`, capping each mapped invocation independently.
- Downstream of the fan-out, a normal edge from the worker node to a "reduce" node runs once after all parallel invocations complete (superstep barrier), so the reducer node sees the fully merged key.
- Idempotency caveat (same page): nodes may re-execute after interrupts/resumes, so mapped workers with side effects should be idempotent.

## Notable quotes

> "The Send class facilitates dynamically invoking a node with a custom state at the next step." — LangGraph reference
> "The sent state can differ from the core graph's state." — LangGraph reference

## Application to Ouroboros

- **Inspector:** fan out over the files changed in a commit — `[Send("inspect_file", {"path": f, "diff": d}) for f, d in state["changed_files"]]` — each worker returns a per-file finding into an `Annotated[list, add]` key; a reduce node composes the final verdict JSON from the merged findings.
- **Generator:** map over the planned scaffold modules, generating each file's content in parallel, reducing into a manifest key.
- **Inquisitor:** fan out follow-up probes over the gaps detected in an answer, then reduce the probe results into the interview state.
