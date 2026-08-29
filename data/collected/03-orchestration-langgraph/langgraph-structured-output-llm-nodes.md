---
title: Structured Output from LLM Nodes — with_structured_output, Strategies, Validation Retries
source_url: https://docs.langchain.com/oss/python/langchain/structured-output
publisher: LangChain
retrieved: 2026-08-26
domain: orchestration-langgraph
doc_type: official-docs
relevance: The Slop Inspector must emit a schema-valid verdict JSON; this documents how to enforce Pydantic/JSON-schema output from LLM nodes and recover from validation failures.
---

## Summary

LangChain offers two layers for schema-enforced LLM output. At the chat-model
level, `model.with_structured_output(schema)` binds a Pydantic model, TypedDict,
or JSON schema to the model and returns parsed objects instead of free text. At
the agent level, `create_agent(..., response_format=...)` accepts a schema or an
explicit `ProviderStrategy` / `ToolStrategy` and places the result in the
`'structured_response'` key of the final agent state, with built-in retry
messaging when the model emits output that fails schema validation. Pydantic
`BaseModel` schemas give runtime validation; TypedDict and JSON schema return
plain dicts without validation. (with_structured_output details corroborated
against https://docs.langchain.com/oss/python/langchain/models.)

## Key knowledge

- `with_structured_output` parameters:
  - `schema` — Pydantic `BaseModel` subclass, `TypedDict`, or JSON Schema dict.
  - `method` — `"json_schema"` | `"function_calling"` | `"json_mode"` (provider-dependent). `"json_schema"` uses the provider's dedicated structured-output feature; `"function_calling"` forces a tool call carrying the schema; `"json_mode"` only guarantees valid JSON — the schema must be described in the prompt.
  - `include_raw: bool` — default `False`.
  - `strict` — available for certain providers; enables strict schema adherence.
- Return type by schema kind: Pydantic `BaseModel` → validated Pydantic instance (runtime validation, field descriptions, nested structures); `TypedDict` → dict (no runtime validation); JSON Schema dict → dict. Dataclasses (agent path) → dict.
- With `include_raw=True` the invocation returns:
  ```python
  {
      "raw": AIMessage(...),   # raw model response
      "parsed": <ParsedType>,  # structured output, or None on failure
      "parsing_error": None,   # the exception if parsing/validation failed
  }
  ```
  This is the hook for custom retry loops: check `parsing_error`, feed the error text back to the model, re-invoke.
- Agent-level API — `create_agent` signature fragment:
  ```python
  response_format: Union[
      ToolStrategy[StructuredResponseT],
      ProviderStrategy[StructuredResponseT],
      type[StructuredResponseT],
      None,
  ]
  ```
  Result lands in the `'structured_response'` key of the agent's final state.
- `ProviderStrategy` (native provider structured output — OpenAI, Anthropic, xAI, Gemini):
  ```python
  class ProviderStrategy(Generic[SchemaT]):
      schema: type[SchemaT]
      strict: bool | None = None   # strict adherence; requires langchain>=1.2
  ```
- `ToolStrategy` (fallback via tool calling, for models without native support):
  ```python
  class ToolStrategy(Generic[SchemaT]):
      schema: type[SchemaT]
      tool_message_content: str | None
      handle_errors: Union[
          bool, str,
          type[Exception], tuple[type[Exception], ...],
          Callable[[Exception], str],
      ]
  ```
- `handle_errors` semantics (validation-failure retry policy):
  - `True` (default) — catch all errors, retry with a default feedback template.
  - `str` — catch all errors, retry with this custom message.
  - `type[Exception]` / tuple of exception types — catch only those types.
  - `Callable[[Exception], str]` — compute the retry feedback message.
  - `False` — no retry; exceptions propagate.
- Automatic strategy selection: passing a bare schema type to `response_format` picks `ProviderStrategy` when the model natively supports structured output, else `ToolStrategy`. Model capability is read from profile data; custom profiles can override.
- Automatic error recovery in the agent path: multiple structured outputs in one turn → model is prompted to retry with a single output; schema validation errors → the model receives specific feedback about what failed.
- Union types as schema (multiple possible response shapes) are supported by `ToolStrategy` only.
- Gotcha: raw JSON Schema dicts require `title` and `description` fields, and "JSON Schema dictionaries must be wrapped in an explicit strategy; they are not automatically detected" when passed to `response_format`.

## Notable quotes

> "Pydantic BaseModel provides the richest feature set with field validation, descriptions, and nested structures." — LangChain docs
> "TypedDict is a simpler alternative to Pydantic models, ideal when you don't need runtime validation." — LangChain docs
> "JSON Schema dictionaries must be wrapped in an explicit strategy; they are not automatically detected." — LangChain docs

## Application to Ouroboros

- **Inspector (critical):** the verdict node should define the verdict schema as a Pydantic `BaseModel` with `Field(description=...)` on every field and call `llm.with_structured_output(VerdictSchema, include_raw=True)`. Check `parsing_error`; on failure, re-invoke with the validation error appended — or set `strict=True` on Anthropic/OpenAI models for provider-enforced schemas.
- **Inquisitor:** interview-turn outputs (next question, coverage flags, done-signal) fit a small Pydantic schema so the conditional edge can route on typed fields instead of parsing prose.
- **Generator:** file-plan / scaffold-manifest outputs can use `ToolStrategy(handle_errors=True)` semantics to self-heal malformed plans rather than crashing the graph.
