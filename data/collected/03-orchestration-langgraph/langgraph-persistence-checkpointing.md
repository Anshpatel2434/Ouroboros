---
title: LangGraph Persistence — Checkpointers, Threads, Time Travel, Stores
source_url: https://docs.langchain.com/oss/python/langgraph/persistence
publisher: LangChain
retrieved: 2026-08-25
domain: orchestration-langgraph
doc_type: official-docs
relevance: Ouroboros interviews and inspection runs must survive process restarts and support resume; checkpointer choice and thread config are the mechanism.
---

## Summary

LangGraph persistence has two complementary layers: checkpointers, which
snapshot the entire graph state after every super-step into a thread (short-term,
thread-scoped memory), and stores, which hold application-defined key-value data
shared across threads (long-term memory). A checkpointer compiled into a graph
enables conversation continuity, human-in-the-loop interrupts, time travel
(replay and fork from any checkpoint), and fault tolerance (resume from the last
successful step). Production deployments use the SQLite or Postgres checkpointer
packages instead of the in-memory saver.

## Key knowledge

- Checkpointer packages and classes (Python):
  - `langgraph-checkpoint` (bundled with LangGraph): `InMemorySaver` — RAM only; all checkpoints lost on process restart. Dev/test only.
  - `langgraph-checkpoint-sqlite`: `SqliteSaver`, `AsyncSqliteSaver` — file-based, survives restarts, good for local/dev workloads.
  - `langgraph-checkpoint-postgres`: `PostgresSaver`, `AsyncPostgresSaver` — production-grade.
- Postgres setup:
  ```python
  checkpointer = PostgresSaver.from_conn_string("postgresql://...")
  checkpointer.setup()  # one-time: creates tables + indexes
  ```
- Wire in at compile time: `graph = builder.compile(checkpointer=checkpointer)`.
- Thread config shape (required with a checkpointer): `{"configurable": {"thread_id": "1"}}`. To target a specific checkpoint: `{"configurable": {"thread_id": "1", "checkpoint_id": "<uuid>"}}`. Gotcha: with `PostgresSaver`, keep `thread_id` under 255 characters (column length limit) — UUIDs recommended.
- A checkpoint is a snapshot of graph state at a point in time with a unique, monotonically increasing ID; one checkpoint is saved per super-step.
- `StateSnapshot` fields: `values` (state channel values), `next` (tuple of node names to execute next), `config` (checkpoint's config incl. checkpoint_id), `metadata`, `created_at`, `parent_config` (previous checkpoint), `tasks` (tuple of `PregelTask` objects with pending-task info and error details).
- State inspection/mutation methods on a compiled graph:
  - `graph.get_state(config)` → latest `StateSnapshot` for the thread (or the specific checkpoint if `checkpoint_id` given).
  - `graph.get_state_history(config)` → all snapshots for the thread, most recent first.
  - `graph.update_state(config, values, as_node=...)` → patch state; keys with reducers apply the reducer (append), keys without are overwritten; `as_node` controls which node the update is attributed to (affects what runs next).
- Time travel / forking: invoking with a `checkpoint_id` in config replays already-executed steps up to that checkpoint without re-running them, then executes steps after it as a new fork — even if they ran before.
- Fault tolerance / pending writes: if one node in a super-step fails, writes from the nodes that succeeded in that step are preserved as pending writes, so resuming the thread does not re-execute the successful nodes.
- Store (cross-thread memory):
  - Interface `BaseStore`; in-memory implementation `InMemoryStore`. Pass alongside the checkpointer at compile time; access inside nodes by declaring a `store: BaseStore` parameter.
  - Namespaces are tuples, e.g. `(user_id, "memories")`.
  - `store.put(namespace, key, value)`; `store.search(namespace, query=..., limit=...)` with optional semantic matching. Items carry `value`, `key`, `namespace`, `created_at`, `updated_at`.
  - Semantic search enabled with an index config: `{"embed": "provider:model", "dims": 1536, "fields": ["field_name", "$"]}`.
- Serialization: default `JsonPlusSerializer` handles LangChain/LangGraph primitives, datetimes, enums; `pickle_fallback` arg covers other types. `EncryptedSerializer.from_pycryptodome_aes()` encrypts checkpoints using the `LANGGRAPH_AES_KEY` env var.
- Operational gotchas: checkpoints accumulate per thread — prune periodically to control storage cost; parent graphs and subgraphs do not share state directly — use a Store for cross-graph data.

## Notable quotes

> "MemorySaver and InMemorySaver store checkpoints in RAM. When the process restarts, all checkpoints are lost." — LangChain docs

## Application to Ouroboros

The Inquisitor needs `SqliteSaver` (local dev) or `PostgresSaver` (deployed) so
a founder can pause an interview and resume days later on the same `thread_id`;
its `interrupt()`-based question loop is impossible without a checkpointer. The
runner uses `get_state`/`get_state_history` to show progress and to fork a
Generator run from an earlier checkpoint after a bad scaffold decision. The Slop
Inspector stores per-repo learned conventions in a `BaseStore` namespace keyed by
repo so knowledge persists across inspection threads.
