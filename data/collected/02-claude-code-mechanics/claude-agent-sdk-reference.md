---
title: Claude Agent SDK (Python & TypeScript) — programmatic agentic loops
source_url: https://code.claude.com/docs/en/agent-sdk/overview
publisher: Anthropic
retrieved: 2026-08-26
domain: claude-code-mechanics
doc_type: official-docs
relevance: Ouroboros's runner can embed Claude Code as a library instead of shelling out to `claude -p` — this is the full option surface for driving sessions, permissions, resume, and cost caps programmatically.
---

## Summary

The Claude Agent SDK packages Claude Code's agent loop, tools, and context management as a library for Python (`claude-agent-sdk`) and TypeScript (`@anthropic-ai/claude-agent-sdk`). It offers a one-shot `query()` function and a persistent client (`ClaudeSDKClient` in Python; a `Query` async-generator object in TypeScript) for multi-turn conversations with interrupts. Everything Claude Code supports — hooks, subagents, MCP servers, permission rules and modes, skills, plugins, session resume/fork — is exposed through an options object (`ClaudeAgentOptions` / `Options`). The SDK spawns the Claude Code CLI as a subprocess; for other languages Anthropic recommends running `claude -p --output-format json` directly. Anthropic does not allow third parties to offer claude.ai login/rate limits through SDK-built agents; use API-key auth. Also covered here: the Python reference (code.claude.com/docs/en/agent-sdk/python) and TypeScript reference (code.claude.com/docs/en/agent-sdk/typescript).

## Key knowledge

### Packages and install
- Python: `pip install claude-agent-sdk` (needs a venv on PEP 668 systems). TypeScript: `npm install @anthropic-ai/claude-agent-sdk` (ships platform-specific binaries like `@anthropic-ai/claude-agent-sdk-darwin-arm64`).
- Positioning: Agent SDK = library running the agent loop in your process; CLI = interactive terminal; Client SDK = raw API, you build the loop; Managed Agents = Anthropic-hosted REST API + sandbox.
- Changelogs/issues: github.com/anthropics/claude-agent-sdk-python and claude-agent-sdk-typescript.

### Python `query()` and `ClaudeSDKClient`
- `async def query(*, prompt: str | AsyncIterable[dict], options: ClaudeAgentOptions | None = None, transport: Transport | None = None) -> AsyncIterator[Message]` — new session per call; use for one-off tasks. Streaming input is supported by passing an async iterable of message dicts.
- `ClaudeSDKClient(options=None, transport=None)` — persistent session, supports `async with`. Methods: `connect(prompt=None)`, `query(prompt, session_id="default")`, `receive_messages()`, `receive_response()`, `interrupt()`, `set_permission_mode(mode)`, `set_model(model=None)`, `rewind_files(user_message_id)`, `get_mcp_status()`, `reconnect_mcp_server(name)`, `toggle_mcp_server(name, enabled)`, `stop_task(task_id)`, `get_server_info()`, `disconnect()`.
- Gotcha: don't `break` out of the message iteration loop (asyncio cleanup issues); let iteration finish or use a flag.
- Session utilities (module-level): `list_sessions(directory, limit, offset, include_worktrees)`, `get_session_messages(session_id, ...)`, `get_session_info(session_id, ...)`, `rename_session(session_id, title, ...)`, `tag_session(session_id, tag, ...)`.

### `ClaudeAgentOptions` fields (Python, snake_case)
- Tools/permissions: `tools` (list or preset `{"type": "preset", "preset": "claude_code"}`), `allowed_tools: list[str]` (auto-approve), `disallowed_tools: list[str]` (supports scoped rules like `"Bash(rm *)"`), `permission_mode` (`"default" | "acceptEdits" | "plan" | "dontAsk" | "bypassPermissions" | "auto"`), `can_use_tool` (permission callback), `permission_prompt_tool_name`.
- Prompting: `system_prompt` — a plain string, `{"type": "preset", "preset": "claude_code", "append": "...", "exclude_dynamic_sections": bool}`, or `{"type": "file", "path": "..."}` (use the file form for prompts >128 KB to dodge OS argv limits).
- Sessions: `continue_conversation: bool` (resume most recent), `resume: str` (session ID), `fork_session: bool` (new ID on resume), `resume_session_at: str` (load only up to a message UUID), `resume_drops_turn: str`, `session_id: str` (must be a valid UUID), `session_store` / `session_store_flush` (`"batched" | "eager"`) to mirror transcripts to an external backend, `load_timeout_ms` (default 60000), `enable_file_checkpointing: bool` (enables `rewind_files`).
- Limits: `max_turns: int`, `max_budget_usd: float` (stop at estimated cost), `task_budget` (`{"total": <int>}` API-side token budget, alpha), `max_buffer_size` (CLI stdout buffering).
- Environment: `cwd`, `cli_path`, `settings` (settings file path), `setting_sources: list["user"|"project"|"local"]` (None loads all three + managed policy; restrict to avoid executing a target repo's config), `add_dirs`, `env: dict` (supports `API_TIMEOUT_MS` default 600000, `CLAUDE_CODE_MAX_RETRIES` default 10 cap 15, `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`, `CLAUDE_ENABLE_STREAM_WATCHDOG`, `CLAUDE_STREAM_IDLE_TIMEOUT_MS` min/default 300000), `extra_args` (arbitrary CLI flags), `user`, `stderr` (callback).
- Model: `model`, `fallback_model`, `effort` (`"low"|"medium"|"high"|"xhigh"|"max"`), `thinking` (`{"type": "adaptive"|"enabled"|"disabled", "budget_tokens": int, "display": "summarized"|"omitted"}`; `max_thinking_tokens` is deprecated).
- Extensions: `mcp_servers` (dict, or path to config file), `strict_mcp_config: bool` (ignore project MCP config), `agents: dict[str, AgentDefinition]` (programmatic subagents — note its fields are camelCase: `description`, `prompt`, `tools`, `disallowedTools`, `model`, `skills`, `memory`, `mcpServers`, `initialPrompt`, `maxTurns`, `background`, `effort`, `permissionMode`), `skills` (list or `"all"`), `plugins`, `hooks: dict[HookEvent, list[HookMatcher]]`, `sandbox`, `betas`.
- Output/streaming: `include_partial_messages` (emit `StreamEvent`), `include_hook_events`, `forward_subagent_text` (SDK ≥0.2.140), `output_format` (`{"type": "json_schema", "schema": {...}}` for structured output).

### Messages (Python)
- `AssistantMessage.content: list[TextBlock | ToolUseBlock | ThinkingBlock]` (`ToolUseBlock` has `id`, `name`, `input`).
- `ResultMessage`: `result`, `total_cost_usd`, `session_id`, `num_turns`, `subtype` (e.g. `"success"`), `terminal_reason` (e.g. `"aborted_streaming"`, `"aborted_tools"`).
- Also `UserMessage`, `ToolResultMessage`, `TaskNotificationMessage` (background task status), `StreamEvent`, `HookEventMessage`.

### Custom in-process tools and permission callbacks (Python)
- `@tool(name, description, input_schema, annotations=None)` decorator + `create_sdk_mcp_server(name, version="1.0.0", tools=[...]) -> McpSdkServerConfig` (`{"type": "sdk", "name": ..., "instance": ...}`) — runs an MCP server inside your process; pass it in `mcp_servers`.
- `can_use_tool` callback: `(tool_name, input_data, ToolPermissionContext) -> PermissionResultAllow | PermissionResultDeny`. Only invoked when the permission flow would prompt — not for auto-approved calls. `PermissionResultAllow` can return `updated_input` and `updated_permissions`; `PermissionResultDeny` has `message` and `interrupt`. `PermissionUpdate` types: `addRules`, `replaceRules`, `removeRules`, `setMode`, `addDirectories`, `removeDirectories`, with `destination` one of `userSettings|projectSettings|localSettings|session`.

### TypeScript specifics
- `query({ prompt: string | AsyncIterable<SDKUserMessage>, options?: Options }): Query` — `Query` is an `AsyncGenerator<SDKMessage>` plus control methods: `interrupt()`, `rewindFiles()`, `setPermissionMode()`, `setModel()`, `applyFlagSettings()`, `streamInput()`. Dynamic control methods work only in streaming-input mode.
- Options are camelCase: `systemPrompt`, `allowedTools`, `disallowedTools`, `permissionMode`, `canUseTool`, `allowDangerouslySkipPermissions`, `cwd`, `env`, `executable` (`'bun'|'deno'|'node'`), `pathToClaudeCodeExecutable`, `abortController`, `mcpServers`, `strictMcpConfig`, `settingSources`, `settings`, `managedSettings`, `additionalDirectories`, `maxTurns`, `maxBudgetUsd`, `model`, `effort`, `thinking`, `outputFormat`, `continue`, `resume`, `resumeSessionAt`, `forkSession`, `sessionId`, `title`, `persistSession`, `includePartialMessages`, `forwardSubagentText`, `agents`, `agent`, `hooks`, `plugins`, `skills`, `sandbox`, `enableFileCheckpointing`, `sessionStore`, `sessionStoreFlush`, `spawnClaudeCodeProcess`, `toolAliases`, `toolConfig`.
- Helpers: `listSessions()`, `getSessionMessages()`, `getSessionInfo()`, `renameSession()`, `tagSession()`, `resolveSettings()` (snapshot merged settings without spawning; always reads `settings.local.json` from the starting directory, not the repo root), `startup()` (pre-warm the CLI subprocess), `tool()` (Zod schemas), `createSdkMcpServer()`.

### Cross-cutting behaviors
- SDK sessions never show the workspace-trust dialog; they load a repo's `.mcp.json` servers without asking (when `settingSources`/`setting_sources` includes project). Restrict sources or use `--bare`-equivalent isolation for untrusted generated repos.
- Sessions created by the SDK don't appear in the interactive session picker or `claude --continue`, but can be resumed by explicit session ID.
- Additional directories passed via the SDK behave like `--add-dir`: they load skills/commands/subagents through the `project` setting source.

## Notable quotes

> "The Agent SDK gives you the same tools, agent loop, and context management that power Claude Code, programmable in Python and TypeScript." — Agent SDK overview

> "Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK." — Agent SDK overview

> "Use `ClaudeSDKClient` for continuous conversations; `query()` creates a new session per call." — Python SDK reference

## Application to Ouroboros

The runner is the primary consumer: it can replace raw `claude -p` subprocess management with `ClaudeSDKClient`, gaining typed `ResultMessage` cost/turn telemetry (`total_cost_usd`, `num_turns`, `session_id`), `interrupt()`, `max_budget_usd`/`max_turns` guardrails, and `resume`/`fork_session` for long multi-phase runs. The Inspector consumes `can_use_tool` and `hooks` as programmatic guardrails (deny/modify tool calls in-process instead of shelling out to hook scripts). The Generator should emit harness repos whose configs are loaded via `setting_sources=["project"]` only, and Inquisitor prompts can be injected through `system_prompt` preset+append so Claude Code's native system prompt is retained.
