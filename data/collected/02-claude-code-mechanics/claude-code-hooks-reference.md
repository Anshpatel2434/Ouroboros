---
title: Claude Code hooks reference (events, config, exit codes, JSON output)
source_url: https://code.claude.com/docs/en/hooks
publisher: Anthropic
retrieved: 2026-08-25
domain: claude-code-mechanics
doc_type: official-docs
relevance: Hooks are Ouroboros's primary deterministic guard-rail mechanism — the Generator emits PreToolUse/PostToolUse/Stop hooks into every harness repo.
---

## Summary

Full reference for Claude Code hooks: shell commands (and HTTP/MCP/prompt/agent handlers) that Claude Code executes at fixed lifecycle events regardless of what the model decides. Covers the settings.json configuration shape, all hook events (PreToolUse, PostToolUse, Stop, SessionStart, PreCompact, WorktreeCreate, etc.), the JSON delivered on stdin, exit-code semantics (0 = success/JSON honored, 2 = block, other = non-blocking), and the structured JSON output fields (`permissionDecision`, `additionalContext`, `updatedInput`, `stopReason`) that let hooks deny tools, inject context, rewrite input, or prevent the agent from stopping.

## Key knowledge

### Hook events
- Lifecycle: `SessionStart`, `SessionEnd`, `Setup`.
- Per-turn: `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `StopFailure`.
- Tool execution: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`, `PostToolBatch`.
- Others: `Notification`, `MessageDisplay`, `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `FileChanged`, `DirectoryAdded`, `WorktreeCreate`, `WorktreeRemove`, `PreCompact`, `PostCompact`, `Elicitation`, `ElicitationResult`.

### settings.json configuration shape
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(rm *)",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-rm.sh",
            "args": [],
            "async": false,
            "shell": "bash",
            "timeout": 600,
            "statusMessage": "Checking permissions..."
          }
        ]
      }
    ]
  },
  "disableAllHooks": false
}
```
- Handler `type` values: `"command"` (shell), `"http"` (POST endpoint, with `url`, `headers` supporting `$VAR` interpolation, `allowedEnvVars`), `"mcp_tool"` (`server`, `tool`, `input` with `${tool_input.file_path}`-style substitution), `"prompt"` (LLM check, `$ARGUMENTS` = hook input JSON, default timeout 30s), `"agent"` (subagent check, default timeout 60s).
- Common fields: `if` (permission-rule filter, tool events only, e.g. `"Edit(*.ts)"`), `timeout` seconds (default 600 for command/http/mcp_tool), `statusMessage`, `once` (skill frontmatter only).
- Command handler extras: `args` (presence → exec form, no shell), `async` (background, non-blocking), `asyncRewake` (background hook that wakes Claude on exit code 2), `shell`: `"bash"` | `"powershell"`.
- Hook sources merged (not replaced): `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`, managed policy, plugin `hooks/hooks.json`, skill/subagent frontmatter. `"disableAllHooks": true` kills all.
- Path placeholders: `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`.

### Matcher semantics
- `"*"`, `""`, or omitted = match all. Alphanumeric/`|`/`,` strings = exact name or list (`"Edit|Write"`). Anything else = unanchored JS regex (`"mcp__memory__.*"`).
- What matchers match, per event: tool events → tool name; `SessionStart` → `"startup"`, `"resume"`, `"clear"`, `"compact"`, `"fork"`; `SessionEnd` → `"clear"`, `"resume"`, `"logout"`, `"prompt_input_exit"`; `Notification` → `"permission_prompt"`, `"idle_prompt"`, ...; `SubagentStart`/`SubagentStop` → agent type name; `ConfigChange` → `"user_settings"`, `"project_settings"`, `"local_settings"`, `"policy_settings"`, `"skills"`; `StopFailure` → `"rate_limit"`, `"overloaded"`, `"authentication_failed"`, `"billing_error"`. `UserPromptSubmit`, `PostToolBatch`, `CwdChanged` take no matcher.
- MCP tool names: `mcp__<server>__<tool>`; plugin-scoped: `mcp__plugin_<plugin>_<server>__<tool>`.

### Hook input (stdin JSON)
Common fields: `session_id`, `prompt_id` (UUID, matches OTel correlation), `transcript_path` (JSONL path, may lag current turn), `cwd` (follows worktrees/`cd`), `permission_mode` (`"default"|"plan"|"acceptEdits"|"auto"|"dontAsk"|"bypassPermissions"`), `hook_event_name`, optional `agent_id`/`agent_type` (subagent context), `effort.level`.
Tool events add: `tool_name`, `tool_input` (full tool args object), `tool_use_id`, `tool_call_index`, `tool_output` / `tool_error` (post events).

### Exit code semantics
- **0**: success; stdout starting with `{` parsed as JSON (invalid JSON → treated as plain text, non-blocking).
- **2**: blocking error — blocks the action by exit code alone (stdout JSON NOT honored). Per event: `PreToolUse` blocks the tool call; `UserPromptSubmit` rejects the prompt; `Stop`/`SubagentStop` prevents stopping and forces continuation; `PostToolBatch` stops the agentic loop before the next model call; `PreCompact` blocks compaction; `ConfigChange` blocks the change; `WorktreeCreate` any non-zero fails creation. `PostToolUse`/`PostToolUseFailure`: tool already ran — stderr is shown to Claude. `PermissionRequest`/`PermissionDenied`: exit 2 ignored (use JSON).
- **Other non-zero**: non-blocking; continues.
- **Timeout**: hook canceled, no decision, action continues normally.

### JSON output fields
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Destructive command blocked",
    "updatedInput": {"command": "modified-command"},
    "additionalContext": "Info added to conversation"
  }
}
```
- `PreToolUse`: `permissionDecision`: `"allow" | "deny" | "escalate"`, plus `permissionDecisionReason`, `updatedInput` (rewrite tool input), `additionalContext`.
- `PostToolUse`/`PostToolUseFailure`: `additionalContext` (feedback into transcript).
- `PermissionRequest`: `decision`: `"allow" | "deny" | "escalate"`.
- `PermissionDenied`: `retry: true` (model may retry denied call).
- `Stop`/`SubagentStop`: `stopReason`: `"completed" | "user_stop"`.
- `UserPromptSubmit`: `updatedPrompt` (rewrite user prompt).
- Universal: `systemMessage` (shown to Claude on most events; ignored for `SessionStart`, `SessionEnd`, `StopFailure`, `Notification`, `PermissionDenied`, `Elicitation`), `terminalSequence` (ANSI, runs on all exit codes).

### Example: block `rm -rf` (PreToolUse deny)
```bash
#!/bin/bash
COMMAND=$(jq -r '.tool_input.command')
if echo "$COMMAND" | grep -q 'rm -rf'; then
  jq -n '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:"Destructive command blocked by hook"}}'
else
  exit 0
fi
```
Registered with `"matcher": "Bash"` and `"if": "Bash(rm *)"`. Post-edit linting: matcher `"Edit|Write"` on `PostToolUse` with a command hook.

## Notable quotes

> "Exit code 2 ... Block action (event-dependent). No; code alone blocks."

> "Settings rules are enforced by the client regardless of what Claude decides to do."

## Application to Ouroboros

Hooks are the enforcement layer the Generator writes into every harness repo: `PreToolUse` command hooks (with `permissionDecision: "deny"`) to block destructive commands and protected paths; `PostToolUse` on `Edit|Write` to run linters/tests and feed failures back via `additionalContext`; `Stop` hooks with exit 2 to keep the loop running until acceptance criteria pass (the core "don't stop until done" pattern for autonomous sessions); `SessionStart` with matcher `compact` to re-inject harness instructions after compaction; `PostToolBatch` as a circuit breaker that halts the agentic loop. The Inspector can consume `transcript_path` from hook input for live drift analysis, and the runner can use `StopFailure` matchers (`rate_limit`, `billing_error`) for failure-mode telemetry.
