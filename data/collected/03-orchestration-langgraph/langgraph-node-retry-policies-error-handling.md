---
title: Node Fault Tolerance — RetryPolicy, TimeoutPolicy, error_handler, CachePolicy
source_url: https://docs.langchain.com/oss/python/langgraph/fault-tolerance
publisher: LangChain
retrieved: 2026-08-26
domain: orchestration-langgraph
doc_type: official-docs
relevance: Ouroboros graphs call flaky externals (LLM APIs, git, GitHub); per-node retries, timeouts, and fallback handlers keep interviews and inspections from dying on transient errors.
---

## Summary

LangGraph attaches fault tolerance directly to nodes via three composable
primitives passed to `add_node`: `RetryPolicy` (exponential-backoff retries on
transient exceptions), `TimeoutPolicy` (wall-clock and idle caps per attempt),
and `error_handler` (custom compensation logic that runs only after retries are
exhausted and can rewrite state or reroute via `Command`). Defaults for a whole
graph are set once with `set_node_defaults`, with per-node values overriding.
A separate `CachePolicy` on `add_node` plus a cache at `compile()` time skips
re-running expensive nodes on identical input. (Corroborated against the
LangChain engineering blog "Fault Tolerance in LangGraph" at
https://www.langchain.com/blog/fault-tolerance-in-langgraph.)

## Key knowledge

- Import: `from langgraph.types import RetryPolicy, TimeoutPolicy` (`RetryPolicy` is a NamedTuple, added in langgraph 0.2.24).
- `RetryPolicy` fields and defaults:
  - `max_attempts: int = 3` (includes the first attempt)
  - `initial_interval: float = 0.5` (seconds)
  - `backoff_factor: float = 2.0`
  - `max_interval: float = 128.0` (seconds)
  - `jitter: bool = True`
  - `retry_on` = `default_retry_on` — exception type, sequence of types, or callable `(Exception) -> bool`
- `default_retry_on` behavior: retries any exception **except** `ValueError`, `TypeError`, `ArithmeticError`, `ImportError`, `LookupError`, `NameError`, `SyntaxError`, `RuntimeError`, `ReferenceError`, `StopIteration`, `StopAsyncIteration`, `OSError`; for `requests`/`httpx` it retries only 5xx status codes. `NodeTimeoutError` is retryable by default. Rationale: excluded types are almost always programming bugs, not transient faults.
- Attach to a node:
  ```python
  builder.add_node(
      "call_llm",
      call_llm,
      retry_policy=RetryPolicy(max_attempts=4, backoff_factor=2.0),
  )
  ```
  `retry_policy` can also take a custom tuple: `RetryPolicy(retry_on=(ConnectionError, TimeoutError))`.
- `TimeoutPolicy` fields (langgraph>=1.2 for per-node timeouts):
  - `run_timeout: float | timedelta | None = None` — hard wall-clock cap per single attempt; never refreshed.
  - `idle_timeout: float | timedelta | None = None` — max time without observable progress; under `refresh_on="auto"` it resets on channel writes, streamed chunks, callbacks, and child task events.
  - `refresh_on: "auto" | "heartbeat" = "auto"`
  - Expiry raises `NodeTimeoutError` (which the default retry policy will retry).
- `error_handler` (langgraph>=1.2): runs **only after retries are exhausted** (or the exception is non-retryable):
  ```python
  def on_call_llm_failed(state: State, error: NodeError) -> State:
      return {"status": "llm_unavailable"}

  builder.add_node("call_llm", call_llm,
                   retry_policy=RetryPolicy(max_attempts=4),
                   error_handler=on_call_llm_failed)
  ```
  - `NodeError` is a frozen dataclass: `node: str` (failed node name), `error: BaseException`.
  - Handler signatures `(state)`, `(state, runtime)`, `(state, error)` all accepted; the return value is a state update, or a `Command(update=..., goto=...)` for routing (fallback paths, SAGA-style compensation).
  - Handlers cannot nest (a handler's own failure is not re-handled), and error handlers run atomically in the same execution cycle as the failure; the checkpoint write happens after the handler completes (retry loops themselves are not checkpointed).
- Graph-wide defaults (langgraph>=1.2):
  ```python
  StateGraph(State).set_node_defaults(
      retry_policy=RetryPolicy(max_attempts=3),
      error_handler=default_error_handler,
      timeout=TimeoutPolicy(run_timeout=30),
  )
  ```
  Per-node arguments override defaults; nodes that are themselves error handlers do not inherit `error_handler` or `cache_policy` defaults (prevents recursion and unsafe caching).
- Execution order on failure: attempt → `RetryPolicy` decides retry (backoff + jitter between attempts, timeouts enforced per attempt) → retries exhausted → `error_handler` fires → handler routes/updates or the exception bubbles and the run fails (resumable from the last checkpoint if a checkpointer is attached).
- Node caching (`from langgraph.types import CachePolicy`, graph-api docs):
  ```python
  CachePolicy(key_func=None, ttl=None)  # key: hash of input by default; ttl seconds, None = never expires
  builder.add_node("expensive_node", func, cache_policy=CachePolicy(ttl=3))
  graph = builder.compile(cache=InMemoryCache())  # langgraph.cache.memory
  ```
  Cached hits are marked in stream output with `'__metadata__': {'cached': True}`.
- Idempotency gotcha: retries and post-interrupt resumes re-execute the node body from the top, so side-effectful nodes (API writes, git operations) must be idempotent or guarded.

## Notable quotes

> "Run timeout is a hard wall-clock cap on a single attempt. It is never refreshed." — LangChain docs
> "The error handler is scheduled immediately alongside any other nodes that were already running in that step." — LangChain blog
> Retry and compensation are independent: "configure when to retry and when to compensate independently." — LangChain docs

## Application to Ouroboros

- **All graph runners:** set `set_node_defaults(retry_policy=RetryPolicy(max_attempts=3), timeout=TimeoutPolicy(run_timeout=...))` so every LLM/API node survives transient 5xx and connection drops without per-node boilerplate.
- **Inspector:** the verdict-emitting node gets an `error_handler` that writes a degraded-but-schema-valid verdict (e.g. `{"status": "inspection_failed"}`) so the pipeline always emits parseable JSON; note Pydantic `ValidationError` is a `ValueError`, so schema failures are *not* retried by the default policy — handle them via the structured-output retry loop, not `RetryPolicy`.
- **Generator:** `CachePolicy` on expensive scaffold-planning nodes avoids re-paying LLM calls when re-running with identical input; git/GitHub side-effect nodes must be idempotent because retries re-run the whole node.
- **Inquisitor:** `idle_timeout` catches hung streaming LLM calls mid-interview instead of blocking the session.
