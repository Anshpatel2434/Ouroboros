---
title: Run Claude Code programmatically (headless / non-interactive mode)
source_url: https://code.claude.com/docs/en/headless
publisher: Anthropic
retrieved: 2026-08-25
domain: claude-code-mechanics
doc_type: official-docs
relevance: Core recipe for how Ouroboros's runner drives Claude Code unattended — `claude -p` flags, output parsing, permission baselines, and session continuation.
---

## Summary

The official guide to running Claude Code non-interactively via `claude -p` (print mode), which is the CLI face of the Agent SDK. It covers pre-approving tools with `--allowedTools`, permission-mode baselines, structured output (`--output-format json` / `stream-json` with `--json-schema`), streaming event shapes (`system/init`, `system/api_retry`, subagent message forwarding), `--bare` mode for reproducible CI runs, SIGTERM/SIGINT semantics, and continuing conversations with `--continue` / `--resume`. This is the primary interface an orchestrator uses to run long unattended Claude Code jobs.

## Key knowledge

### Basic invocation
- `claude -p "prompt"` (or `--print`) runs one non-interactive agentic run and exits. Exit code 0 on success, non-zero on failure; scripts can branch on exit status. Invalid flags error to stderr before the run; in-run failures (e.g. missing auth) are printed as the result on stdout.
- Example with tool pre-approval: `claude -p "Find and fix the bug in auth.py" --allowedTools "Read,Edit,Bash"`.
- `-p` rejects `--bg`; `--cloud` + task description also conflicts with `-p` (but `--cloud <session-id>` with `-p` queues a message into that cloud session and exits).
- Piped stdin is supported (`cat build-error.txt | claude -p '...' > output.txt`) and capped at **10MB**; exceeding it exits non-zero. For larger inputs, write to a file and reference the path.
- Skills/custom commands work in `-p` prompts: include `/skill-name` in the prompt string and it expands before the run. Terminal-only builtins (`/login`) are unavailable. `/model sonnet`, `/effort`, `/config key=value` forms work in `-p` (v2.1.205+).

### `--bare` mode (recommended for scripted/SDK calls)
- `--bare` skips auto-discovery of hooks, skills, custom commands, subagents, plugins, MCP servers, auto memory, and CLAUDE.md — reproducible, faster startup. Will become the default for `-p` in a future release.
- Without `--bare`, a `-p` session runs hooks from the project's `.claude/settings.json` and connects `.mcp.json` servers **even in an untrusted folder** — `-p` shows no trust dialog and no per-server approval prompt. This is a key security gotcha for running generated repos.
- In bare mode Claude Code never reads OAuth credentials/keychain; set `ANTHROPIC_API_KEY` (or `apiKeyHelper` via `--settings`). Bedrock/GCP/Foundry creds still work normally.
- Bare mode keeps Bash + file read + file edit tools. Re-add context explicitly:
  - system prompt: `--append-system-prompt`, `--append-system-prompt-file`
  - settings: `--settings <file-or-json>`
  - MCP: `--mcp-config <file-or-json>`
  - agents: `--agents <json>`
  - plugins: `--plugin-dir <path>`, `--plugin-url <url>`
- Exception: `--add-dir` directories still load skills from their `.claude/skills/` (not `.claude/commands/` or `.claude/agents/`).

### Output formats
- `--output-format text` (default) | `json` | `stream-json`.
- `json` returns result text in `.result`, plus `session_id`, usage metadata, `total_cost_usd` and a per-model cost breakdown (client-side estimates).
- Schema-constrained output: `--output-format json --json-schema '<JSON Schema>'` → structured value in `structured_output` field. Invalid schema exits with `Error: --json-schema is not a valid JSON Schema`; `format` keyword accepted but treated as annotation only (v2.1.205+ behavior).
- Parse with jq: `claude -p "..." --output-format json | jq -r '.result'` or `| jq '.structured_output'`.
- Streaming: `--output-format stream-json --verbose --include-partial-messages` emits newline-delimited JSON events; final line is a `result` message with response text, cost, and session metadata. Filter text deltas: `jq -rj 'select(.type == "stream_event" and .event.delta.type? == "text_delta") | .event.delta.text'`.
- Slow consumers: exit wait scales with queued output, capped at 30s (v2.1.214+).

### Stream events worth monitoring
- `system/init` (first event): session metadata — model, tools, `mcp_servers` (each `{name, status}`), `mcp_server_errors` (skipped `--mcp-config` entries: `{name, type, message}`; omitted when empty → CI can fail on a non-empty array; v2.1.219+), `plugins` / `plugin_errors`, and optional `capabilities` string array for feature detection (v2.1.205+).
- `system/api_retry`: fields `attempt`, `max_retries`, `retry_delay_ms`, `error_status` (HTTP or null), `error` (one of `authentication_failed`, `oauth_org_not_allowed`, `billing_error`, `rate_limit`, `overloaded`, `invalid_request`, `model_not_found`, `server_error`, `max_output_tokens`, `unknown`), `uuid`, `session_id`.
- `system/plugin_install` (when `CLAUDE_CODE_SYNC_PLUGIN_INSTALL` set): `status` = `started` | `installed` | `failed` | `completed`.
- Subagent messages: `assistant`/`user` messages carry `parent_tool_use_id` = spawning tool-call ID (null for main conversation). By default only subagent `tool_use`/`tool_result` blocks are emitted; pass `--forward-subagent-text` or set `CLAUDE_CODE_FORWARD_SUBAGENT_TEXT` (v2.1.211+) to also get subagent text/thinking; nested subagents chain via `parent_tool_use_id` (v2.1.219+).
- With `--mcp-config` + `-p`, Claude Code waits up to `MCP_TIMEOUT` (default 30s) for pending servers before the first turn (v2.1.221+).

### Permissions in `-p`
- `--allowedTools` uses permission rule syntax, e.g. `--allowedTools "Bash(git diff *),Bash(git log *),Bash(git status *),Bash(git commit *)"`. Trailing ` *` is prefix matching; the space matters: `Bash(git diff*)` would also match `git diff-index`.
- `-p` always starts in **Manual** permission mode regardless of plan; set a baseline with `--permission-mode`:
  - `auto`: classifier reviews most actions.
  - `dontAsk`: deny anything not matched by `permissions.allow` rules or the read-only command set — recommended for locked-down CI. `AskUserQuestion`, org-`ask` connector tools, and `requiresUserInteraction` MCP tools are denied even with matching allow rules.
  - `acceptEdits`: file writes auto-approved plus common fs commands (`mkdir`, `touch`, `mv`, `cp`); other shell/network still needs allow rules.
- Example: `claude -p "Apply the lint fixes" --permission-mode acceptEdits`.

### Session continuation
- `--continue` resumes the most recent conversation (skips background sessions); `--resume <session-id>` targets a specific one.
- Capture and reuse an ID: `session_id=$(claude -p "Start a review" --output-format json | jq -r '.session_id')` then `claude -p "Continue" --resume "$session_id"`. Since v2.1.223 the ID is found across any project on the machine (before that, current directory + its worktrees only).

### Process lifecycle
- Background Bash tasks started during a `-p` run are terminated ~5 seconds after the final result; background subagents are waited for, capped at 10 minutes by default (v2.1.182+, tune with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`, `0` = unlimited).
- SIGTERM → exit code 143, in-progress turn left unfinished (no result recorded), running Bash process trees killed, only `SessionEnd` hooks run. Send SIGINT (or SDK `interrupt()`) first to end the turn cleanly. Resuming the session continues the unfinished turn.

## Notable quotes

> "`--bare` is the recommended mode for scripted and SDK calls, and will become the default for `-p` in a future release."

> "A `-p` session shows no workspace trust dialog and no per-server approval prompt."

## Application to Ouroboros

This is the runner's core contract. The runner should invoke generated harness repos with `claude -p --output-format stream-json --verbose`, parse `system/init` to verify hooks/MCP loaded (fail fast on non-empty `mcp_server_errors`), watch `system/api_retry` for rate-limit backoff telemetry, and read `total_cost_usd` per invocation for budget enforcement. The Generator should emit `permissions.allow` rules + `--permission-mode dontAsk` (rather than `--dangerously-skip-permissions`) for locked-down unattended runs, and use `--resume`/`--continue` with captured `session_id`s for multi-phase loops. SIGINT-before-SIGTERM is the correct shutdown sequence for the runner's supervisor. The Inspector can require `--json-schema` structured output for machine-checkable verdicts.
