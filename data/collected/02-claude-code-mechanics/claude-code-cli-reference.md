---
title: Claude Code CLI reference (commands and flags)
source_url: https://code.claude.com/docs/en/cli-reference
publisher: Anthropic
retrieved: 2026-08-25
domain: claude-code-mechanics
doc_type: official-docs
relevance: Canonical flag/subcommand inventory Ouroboros's Generator and runner need to compose correct `claude` invocations.
---

## Summary

Complete reference for the `claude` CLI: subcommands (session management, background sessions, MCP, plugins, auth) and every flag, including print mode, output formats, permission modes, tool restriction, model/budget limits, system-prompt customization, MCP config, subagent definition, and debugging modes. The reference documents which flags require `-p`, which combine with `stream-json`, and version gates for newer flags.

## Key knowledge

### Subcommands (selection relevant to automation)
- `claude` / `claude "query"` — interactive session (optionally with initial prompt).
- `claude -p "query"` — non-interactive query, then exit. `cat file | claude -p "query"` processes piped content.
- `claude -c` / `claude -c -p "query"` — continue most recent conversation in current directory.
- `claude -r "<session>" "query"` — resume session by ID **or name**.
- `claude update`; `claude install [stable|version]` — updates/native install.
- `claude auth login` / `auth logout` / `auth status` (status prints JSON).
- `claude setup-token` — generate a long-lived OAuth token for CI/scripts.
- Background sessions: `claude agents` (monitor parallel sessions, `--json` available), `claude attach <id>`, `claude logs <id>`, `claude stop <id>`, `claude respawn <id>`, `claude rm <id>`, `claude daemon status`, `claude daemon stop --any`.
- `claude mcp` (+ `claude mcp login <name>` / `logout <name>`), `claude plugin`, `claude doctor`, `claude project purge [path]`, `claude import [codex|gemini]`, `claude auto-mode defaults` / `auto-mode reset`.

### Session flags
- `--print` / `-p`; `--resume` / `-r` (ID or name, or interactive picker); `--continue` / `-c` (skips background/SDK//loop sessions; `-p --continue` includes them).
- `--session-id <uuid>` — use a specific session ID (must be a valid UUID).
- `--name` / `-n` — display name; resumable via `claude --resume <name>`.
- `--fork-session` — with `--resume`/`--continue`, create a new session ID instead of appending to the original.
- `--no-session-persistence` — print mode only; no transcript written.

### Output/input flags
- `--output-format text|json|stream-json`; `--input-format text|stream-json`.
- `--verbose`; `--include-partial-messages` (needs `-p` + `stream-json`); `--include-hook-events` (hook lifecycle events into stream); `--forward-subagent-text` (v2.1.211+); `--replay-user-messages` (echo stdin user messages back on stdout; needs stream-json both directions).

### Model/limits
- `--model` — alias (`sonnet`, `opus`, `haiku`, `fable`) or full model name; overrides `model` setting and `ANTHROPIC_MODEL`.
- `--fallback-model sonnet,haiku` — comma-separated fallbacks tried in order when primary is overloaded.
- `--effort low|medium|high|xhigh|max|ultracode`.
- `--max-turns N` — print mode only; exits with error when limit reached.
- `--max-budget-usd 5.00` — print mode only; hard dollar cap per run.
- `--autocompact <auto|token value>` e.g. `--autocompact 500k` (v2.1.221+).

### Permissions & tools
- `--permission-mode default|acceptEdits|plan|auto|dontAsk|bypassPermissions|manual` — overrides `defaultMode` setting.
- `--dangerously-skip-permissions` — equivalent to `--permission-mode bypassPermissions`; persists for background sessions across supervisor restarts.
- `--allow-dangerously-skip-permissions` — adds `bypassPermissions` to the Shift+Tab mode cycle without starting in it.
- `--permission-prompt-tool <mcp_tool_name>` — MCP tool that adjudicates permission prompts in non-interactive mode (waits for its server up to `MCP_TIMEOUT`).
- `--allowedTools` / `--allowed-tools` — allow rules (permission rule syntax), e.g. `"Bash(git log *)" "Read"`.
- `--disallowedTools` / `--disallowed-tools` — bare tool name removes the tool from context; scoped rule (e.g. `Bash(rm *)`) denies matching calls only; `"*"` removes every tool; `"mcp__*"` removes all MCP tools.
- `--tools` — restrict built-in tool set: `""` disables all, `"default"` all, or a list like `"Bash,Edit,Read"`.
- `--add-dir ../apps ../lib` — extra working directories (file access only; most `.claude/` config not discovered; persist via `permissions.additionalDirectories`).

### System prompt flags
- `--system-prompt` / `--system-prompt-file` — replace the entire default prompt.
- `--append-system-prompt` / `--append-system-prompt-file` — append to default.
- `--append-subagent-system-prompt` — append to every subagent's prompt (`-p` only, v2.1.205+).
- `--exclude-dynamic-system-prompt-sections` — move per-machine sections (cwd, env info, memory paths, git flag) into the first user message to improve prompt-cache reuse across machines; only with the default system prompt.

### MCP / plugins / agents
- `--mcp-config <files-or-json>`; `--strict-mcp-config` (only use servers from `--mcp-config`).
- `--plugin-dir <path>`, `--plugin-url <url>` (repeatable, session-only); `--disable-slash-commands`.
- `--agent <name>` — run the main session as a specific agent; `--agents '<json>'` — define subagents dynamically, e.g. `claude --agents '{"reviewer":{"description":"Reviews code","prompt":"You are a code reviewer"}}'`.
- `--chrome` / `--no-chrome` — browser integration toggle.

### Setup / init / settings
- `--init` (run Setup hooks with `init` matcher; print mode), `--init-only` (run Setup + SessionStart hooks then exit), `--maintenance` (Setup hooks with `maintenance` matcher).
- `--settings <file-or-json>` — session-scoped overrides of settings.json keys (file must be ≤2 MiB).
- `--setting-sources user,project,local` — which settings layers load.

### Background & cloud
- `--bg` / `--background` — start as background agent, print session ID and management commands; cannot combine with `-p`. `--bg --exec 'pytest -x'` runs a shell command as a PTY-backed background job.
- `--cloud` — create/target claude.ai web session; `--teleport` — pull a web session into local terminal.
- `--environment ccpool_...` + `--ref <ref>` — self-hosted cloud environments (v2.1.224+).

### Isolation / diagnostics
- `--worktree` / `-w <name>` — run in an isolated git worktree (see worktrees doc); `--tmux` for pane integration.
- `--debug[='mcp,startup']`, `--debug-file <path>`.
- `--safe-mode` — all customizations disabled (CLAUDE.md, skills, plugins, hooks, MCP, output styles...).
- `--bare` — skip auto-discovery for fast, reproducible startup; sets `CLAUDE_CODE_SIMPLE`.
- `--json-schema '<schema>'` — validated structured output (print mode).
- `--betas <names>` — beta API headers (API key users only).

## Notable quotes

> "`--dangerously-skip-permissions` ... persists for background sessions when the supervisor restarts."

> "Mistyped subcommands suggest closest match and exit without starting session."

## Application to Ouroboros

The Generator templates its launch scripts directly from this inventory: `--max-turns` and `--max-budget-usd` are the two native runaway guards for unattended loops, `--settings`/`--setting-sources` let a generated repo pin exactly which settings layers apply, and `--agents` lets the runner inject harness-specific subagents without files. The runner should prefer `--permission-mode` + explicit `--allowedTools` over `--dangerously-skip-permissions`, use `--session-id` to pre-assign deterministic UUIDs for tracking, and use `claude logs/stop/respawn` when managing background sessions. The Inspector can invoke `claude -p` with `--tools` restricted to read-only for review passes.
