---
title: LangGraph Streaming — stream_mode Options, Token Streaming, Custom Writers
source_url: https://docs.langchain.com/oss/python/langgraph/streaming
publisher: LangChain
retrieved: 2026-08-25
domain: orchestration-langgraph
doc_type: official-docs
relevance: Long-running Ouroboros graphs (interviews, scaffold generation, commit inspection) need live progress surfaced to the CLI/UI via stream modes.
---

## Summary

Compiled LangGraph graphs stream via `stream()` (sync) and `astream()` (async),
with a `stream_mode` parameter selecting what is emitted: full state values,
per-node updates, LLM tokens, custom user data, checkpoints, task events, or
debug traces. Multiple modes can be combined in one call, subgraph events can be
included with namespacing, and nodes/tools can push arbitrary progress data
through `get_stream_writer()`. A v2 output format unifies all modes into typed
`StreamPart` chunks.

## Key knowledge

- Methods: `graph.stream(input, config, stream_mode=..., subgraphs=False)` and `graph.astream(...)`; optional `version="v2"` for the unified output format.
- `stream_mode` options:
  - `"values"` — full state dict after each execution step.
  - `"updates"` — only the keys each node changed, keyed by node name.
  - `"messages"` — tuples `(message_chunk, metadata)`: token-by-token LLM output from any LangChain chat model invoked inside nodes.
  - `"custom"` — arbitrary user data emitted via `get_stream_writer()`.
  - `"checkpoints"` — checkpoint events (requires a checkpointer).
  - `"tasks"` — node start/finish events with results/errors.
  - `"debug"` — checkpoints + tasks + extra metadata.
- Multiple modes: `stream_mode=["updates", "custom"]`. Without v2 the iterator yields `(mode, data)` tuples; with v2, every chunk is a `StreamPart`:
  ```python
  {"type": "values|updates|messages|custom|checkpoints|tasks|debug",
   "ns": (),      # namespace tuple for subgraph events
   "data": ...}   # mode-specific payload
  ```
  Branch on `chunk["type"]`.
- Subgraph streaming: pass `subgraphs=True`; nested events carry a namespace path in `ns`, e.g. `("node_name:<task_id>",)`.
- Token streaming filters (in `messages` mode metadata): `metadata["langgraph_node"]` (which node produced it) and `metadata["tags"]`. Exclude a model from streaming with the `nostream` tag: `model.with_config({"tags": ["nostream"]})`.
- Custom progress data from inside a node or tool:
  ```python
  from langgraph.config import get_stream_writer
  writer = get_stream_writer()
  writer({"key": "value"})   # emitted when stream_mode="custom"
  ```
  For non-LangChain LLM SDKs, stream their chunks manually through this writer instead of `messages` mode.
- Python < 3.11 async caveats: pass `RunnableConfig` explicitly to async LLM calls (`ainvoke(config)`), and take `writer: StreamWriter` as a function parameter instead of calling `get_stream_writer()` (context-var propagation limitation).
- v2 `invoke()` returns a `GraphOutput` object with `.value` (final state) and `.interrupts` (tuple), replacing the v1 embedded `__interrupt__` key.

## Notable quotes

No verbatim quotes captured from this source; all facts are recorded in Key
knowledge above.

## Application to Ouroboros

The runner streams every subsystem with `stream_mode=["updates", "messages", "custom"]`:
`updates` drives the step progress display (which node of the Inquisitor or
Inspector is active), `messages` streams question text to the founder as it is
generated, and `custom` writers inside Generator nodes report per-file scaffold
progress ("writing src/api/routes.py"). `subgraphs=True` plus the `ns` namespace
lets the CLI attribute events to the right subsystem. The `nostream` tag keeps
internal judge deliberation in the Slop Inspector from leaking token-by-token to
the user while still streaming the final verdict summary.
