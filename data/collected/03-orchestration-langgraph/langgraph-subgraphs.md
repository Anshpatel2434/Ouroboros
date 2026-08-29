---
title: LangGraph Subgraphs — Composition, State Mapping, Checkpointer Modes
source_url: https://docs.langchain.com/oss/python/langgraph/use-subgraphs
publisher: LangChain
retrieved: 2026-08-25
domain: orchestration-langgraph
doc_type: official-docs
relevance: Each Ouroboros subsystem is a subgraph mounted in the runner's parent graph; state-mapping and checkpointer modes define their contract.
---

## Summary

Subgraphs let a compiled LangGraph be embedded inside another graph, either
directly as a node (when parent and child share state keys) or invoked inside a
wrapper node function that translates between different state schemas. The
subgraph's input/output schemas act as a contract, enabling independent team
development and reuse. Persistence behavior of a subgraph is controlled by the
`checkpointer` argument at its own compile time (inherit per-invocation, persist
per-thread, or stateless), and interrupts, state inspection, and streaming all
work through nested subgraphs.

## Key knowledge

- Two composition patterns:
  1. Shared state keys — pass the compiled subgraph straight to `add_node`:
     ```python
     builder.add_node("node_1", subgraph)
     builder.add_edge(START, "node_1")
     ```
     Parent and subgraph must use identical schemas for the shared channels; the subgraph reads/writes parent state directly.
  2. Different schemas — invoke inside a node function and map keys both ways:
     ```python
     def call_subgraph(state: ParentState):
         out = subgraph.invoke({"bar": state["foo"]})
         return {"foo": out["bar"]}
     ```
     This isolates the subgraph's private keys from the parent.
- Subgraph checkpointer modes (set on the subgraph's own `.compile(checkpointer=...)`):
  - `None` (default) — per-invocation: fresh state each call, but inherits the parent's checkpointer for interrupts within a single invocation.
  - `True` — per-thread: subgraph state accumulates across calls on the same thread (the subgraph "remembers" prior interactions).
  - `False` — stateless: no checkpointing, runs as a plain function, no durable execution.
  - Warning: per-thread subgraphs do not support parallel tool calls; use `ToolCallLimitMiddleware` to prevent conflicts.
- The parent graph must be compiled with a checkpointer for subgraph persistence features (interrupts inside subgraphs, state inspection, per-thread memory) to work.
- Inspect nested state: `graph.get_state(config, subgraphs=True).tasks[0].state`.
- Streaming nested execution: `graph.stream_events(input, version="v3")` exposes `stream.subgraphs` (each with `graph_name`, `path`, and `values` snapshots); alternatively filter raw events by `event["method"] == "updates"` and read `event["params"]["namespace"]`. The classic `.stream(..., subgraphs=True)` includes subgraph outputs with a namespace tuple like `("node_name:<task_id>",)`.
- Interrupts propagate: an `interrupt("continue?")` inside a subgraph node (or a tool used by it) pauses the whole stack; resume with `Command(resume=True)` on the same thread/config.
- Handoffs out of a subgraph route in the parent with `Command(goto=..., graph=Command.PARENT)`.
- Parent and subgraph do not share arbitrary state — cross-graph data belongs in a Store, not the checkpointer.
- Benefits called out: multi-agent systems of independent specialists, per-team ownership behind a stable input/output contract, reuse of node chains across parents, and isolating conversation history per agent.

## Notable quotes

> "As long as the subgraph interface (the input and output schemas) is respected, the parent graph can be built without knowing any details of the subgraph." — LangChain docs

## Application to Ouroboros

The runner mounts Inquisitor, Generator, and Inspector as subgraphs with
*different* schemas (pattern 2): the wrapper node maps the runner's project
state into each subsystem's input (spec in, scaffold out; diff in, verdict out),
keeping interview transcripts and judge scratchpads private. The Inquisitor
compiles with `checkpointer=True` semantics so its interview memory persists
per project thread, while Inspector judge subgraphs compile with
`checkpointer=False` — each commit inspection is a pure function. Interrupt
propagation means a founder-approval interrupt deep inside a subgraph still
surfaces at the runner level.
