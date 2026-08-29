---
title: LangGraph Graph API — StateGraph, Nodes, Edges, Reducers, Send, Command
source_url: https://docs.langchain.com/oss/python/langgraph/graph-api
publisher: LangChain
retrieved: 2026-08-25
domain: orchestration-langgraph
doc_type: official-docs
relevance: Core building blocks for every Ouroboros graph (Inquisitor, Generator, Slop Inspector) — state schemas, routing, and fan-out primitives.
---

## Summary

The Graph API is LangGraph's low-level surface for building agent workflows as
explicit graphs. A `StateGraph` is parameterized by a user-defined state schema;
nodes are plain Python functions that receive the current state and return
partial updates, and edges (static or conditional) decide which node runs next.
State updates are merged through per-key reducers, execution proceeds in
"super-steps" of message passing, and two special primitives — `Send` (dynamic
map-reduce fan-out) and `Command` (combined state update + routing from inside a
node) — cover the dynamic control-flow cases that plain edges cannot.

## Key knowledge

- Constructor: `StateGraph(State, input_schema=None, output_schema=None, context_schema=None)`. The graph is parameterized by a state schema; optional distinct input/output schemas and a runtime context schema.
- Nodes: `add_node(name: str, func: Callable, cache_policy: CachePolicy = None)`. A node function may accept up to three parameters: `state`, `config` (a `RunnableConfig`), and `runtime` (a `Runtime`). It returns a dict of state-key updates (partial update, not full state).
- Edges:
  - `add_edge(source: str, target: str)` — static routing.
  - `add_conditional_edges(source: str, routing_func, mapping=None)` — routing function inspects state and returns the next node name (or a key into the optional `mapping` dict).
  - Entry/exit via constants: `from langgraph.graph import START, END`; e.g. `graph.add_edge(START, "first_node")`, `graph.add_edge("last_node", END)`.
- Compile: `graph.compile(checkpointer=None, cache=None, interrupt_before=None, interrupt_after=None)` — returns the executable graph; compilation is required before invoking.
- State schemas: usually a `TypedDict`; keys may attach a reducer via `Annotated`:
  ```python
  from typing import Annotated
  from langgraph.graph.message import add_messages

  class State(TypedDict):
      messages: Annotated[list, add_messages]
      count: Annotated[int, operator.add]
      status: str  # default reducer: last write wins (replace)
  ```
- Reducers: for each updated key, `new_value = reducer(current_state[key], node_update[key])`. Default reducer replaces the value entirely; common alternatives are `operator.add` (append/sum), `operator.or_`, or any custom callable. `add_messages` additionally tracks message IDs (so re-sending a message with the same ID updates rather than appends) and deserializes message dicts.
- Prebuilt `MessagesState`: `from langgraph.graph import MessagesState`; subclass it to add extra fields alongside the reduced `messages` list.
- `Send` API (map-reduce / dynamic fan-out): `from langgraph.types import Send`. A conditional-edge routing function may return a list of `Send(node_name, custom_state_dict)` objects — one worker node invocation per item, each with its own private input state:
  ```python
  def split_work(state):
      return [Send("process_item", {"item": x}) for x in state["items"]]
  graph.add_conditional_edges("splitter", split_work)
  ```
- `Command` (update + goto from inside a node): `from langgraph.types import Command`. A node can return `Command(update={...}, goto="next_node")` instead of relying on edges. Type-annotate the node as `-> Command[Literal["next_node"]]` so the graph can be rendered/validated. Parameters: `update` (state modifications), `goto` (target node or nodes), `graph=Command.PARENT` (route in the parent graph — used for handoffs out of subgraphs), `resume` (resume value after an `interrupt`).
- Invocation config shape:
  ```python
  config = {
      "configurable": {"thread_id": "unique_id"},
      "recursion_limit": 1000,  # default in v1.0.6+
      "tags": ["debug"],
      "metadata": {...},
  }
  graph.invoke(input_data, config=config)
  ```
- Runtime context: `from langgraph.runtime import Runtime`; a node declared as `def node_func(state: State, runtime: Runtime[ContextSchema])` can read `runtime.context.<field>` (dependency injection of e.g. model provider) and execution info such as the thread id.
- `RemainingSteps` managed value: `from langgraph.managed import RemainingSteps`; a state key annotated with it is auto-populated with the number of steps left before the recursion limit — use it to degrade gracefully instead of hitting a hard `GraphRecursionError`.
- Execution model: message passing in discrete super-steps; all nodes activated in a step run, their updates are reduced, then the next step's nodes are computed.
- Private channels: keys present in internal schemas but not in `output_schema` are excluded from `invoke()` output, though `stream()` can still surface them unless restricted with `output_keys`.
- Idempotency gotcha: after interrupts or retries a node re-executes from its start; side effects inside nodes must be idempotent (upserts / idempotency keys).
- Node caching: `builder.add_node("expensive", func, cache_policy=CachePolicy(ttl=3))` combined with `builder.compile(cache=InMemoryCache())` skips recomputation of identical inputs.

## Notable quotes

> "Nodes execute in super-steps — discrete iterations where active nodes process state and send updates to downstream nodes via edges." — LangChain docs

## Application to Ouroboros

All three subsystems are built on exactly these primitives. The Inquisitor is a
`StateGraph` whose interview state uses `add_messages` for transcript and a
custom reducer for accumulated requirements; the Generator's scaffold plan can
fan out file-generation workers with `Send`; the Slop Inspector's verdict
routing (pass/fail/needs-context) maps directly to `add_conditional_edges` or
`Command(goto=...)`. `RemainingSteps` and `recursion_limit` protect the runner
from unbounded judge/repair loops.
