---
title: MCP server configuration, skills, and slash commands
source_url: https://code.claude.com/docs/en/mcp
publisher: Anthropic
retrieved: 2026-08-26
domain: claude-code-mechanics
doc_type: official-docs
relevance: Generated harness repos ship `.mcp.json` and `.claude/skills/` — this is the exact config grammar, scope model, timeout knobs, and skill frontmatter Ouroboros must emit and the runner must trust-manage.
---

## Summary

Claude Code connects to MCP servers over stdio, HTTP, SSE, or WebSocket, configured via `claude mcp add` or JSON files, at three scopes: local (default, private, stored under the project's entry in `~/.claude.json`), project (shared `.mcp.json` at repo root, committed), and user (`~/.claude.json`, all projects). `.mcp.json` supports `${VAR}` / `${VAR:-default}` expansion in `command`, `args`, `env`, `url`, and `headers`. MCP tools surface as `mcp__<server>__<tool>` and are governed by timeouts (`MCP_TIMEOUT`, `MCP_TOOL_TIMEOUT`, per-server `timeout`) and output caps (`MAX_MCP_OUTPUT_TOKENS`). Skills — `SKILL.md` files with YAML frontmatter — are the merged successor of custom slash commands: `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` both create `/deploy`. Skill bodies load on demand, support `$ARGUMENTS` substitution, tool pre-approval, and forked-subagent execution. Companion page: code.claude.com/docs/en/skills.

## Key knowledge

### Adding MCP servers
- Remote HTTP: `claude mcp add --transport http <name> <url>` (e.g. `claude mcp add --transport http notion https://mcp.notion.com/mcp`); add headers with `--header "X-API-Key: ..."` (`-H`). SSE: same with `--transport sse`. Stdio: `claude mcp add [options] <name> -- <command> [args...]` — everything after `--` runs the server untouched, e.g. `claude mcp add --env AIRTABLE_API_KEY=YOUR_KEY --transport stdio airtable -- npx -y airtable-mcp-server`. Env vars: `-e`/`--env KEY=value`.
- JSON form: `claude mcp add-json <name> '{"command":"npx","args":["-y","@example/mcp-server"]}'` — pass the object *inside* an `mcpServers` block, not the wrapper. WebSocket (`type: "ws"`) is JSON-only (accepts `url`, `headers`, `headersHelper`, `timeout`, `alwaysLoad`; no OAuth).
- Management: `claude mcp list` (shows `✔ Connected` / `! Needs authentication` / `✘ Failed to connect`), `claude mcp get <name>`, `claude mcp remove`, `claude mcp reset-project-choices`, `claude mcp add-from-claude-desktop`. In-session: `/mcp` for status, OAuth 2.0 sign-in, and toggling servers. `type` accepts `streamable-http` as an alias for `http`. Reserved server names rejected: `workspace`, `claude-in-chrome`, `computer-use`, `Claude Preview`, `Claude Browser`.
- Non-OAuth auth: `headersHelper` — a command whose stdout JSON merges into connection headers, e.g. `{"mcpServers": {"internal": {"type": "http", "url": "...", "headersHelper": "/opt/bin/get-mcp-auth-headers.sh"}}}`. In untrusted folders the helper doesn't run until trust is granted.

### Scopes and file shapes
- `--scope`/`-s`: `local` (default) → written under `"projects": {"/path/to/project": {"mcpServers": {...}}}` in `~/.claude.json`; `project` → `.mcp.json` at repo root, standardized shape `{"mcpServers": {"shared-server": {"type": "http", "url": "https://example.com/mcp"}}}`; `user` → `~/.claude.json` top level, all projects.
- Precedence when the same name exists in several places (highest first): local → project → user → plugin servers → claude.ai connectors. Whole entry wins; no field merging.
- Interactive sessions prompt to approve `.mcp.json` servers; `claude -p`, SDK, and cloud sessions load them **without asking**. Block with `disabledMcpjsonServers` (settings, by name), `enabledMcpjsonServers`, or exclude project settings via `--setting-sources` / SDK `settingSources`.
- Env expansion in `.mcp.json`: `${VAR}` and `${VAR:-default}` in `command`, `args`, `env`, `url`, `headers`. Unset var without default → config loads with a missing-variable warning and the literal `${VAR}` text. Plugin configs get `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_PROJECT_DIR}` placeholders.

### Timeouts and output limits
- `MCP_TIMEOUT` (ms): server startup timeout (e.g. `MCP_TIMEOUT=10000 claude`); default 30s (in `-p`, Claude Code waits up to it for pending servers before the first turn).
- Per-server `"timeout"` (ms) in the entry: hard wall-clock per tool call; overrides `MCP_TOOL_TIMEOUT` for that server; values <1000 fall through (default ≈28 h). HTTP/SSE/connector servers also have a 60 s per-request first-byte timer, raised by setting `timeout`/`MCP_TOOL_TIMEOUT` ≥60 s.
- Idle timeout: calls with no response/progress abort — default 5 min for HTTP/SSE/WS/connectors, 30 min for stdio; tune with `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (0 disables).
- Output caps: warning at 10,000 tokens, hard limit 25,000 by default; raise with `MAX_MCP_OUTPUT_TOKENS=50000`.
- Auto-backgrounding: main-conversation MCP calls still running after 2 min move to a background task (v2.1.212+); tune with `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS`; off in `-p` unless `CLAUDE_AUTO_BACKGROUND_TASKS=1`.
- Context: MCP tool definitions are deferred by default (names only until used; `ENABLE_TOOL_SEARCH` controls). Permission rules use `mcp__server` / `mcp__server__tool`.

### Skills (`SKILL.md`)
- Locations: personal `~/.claude/skills/<name>/SKILL.md`, project `.claude/skills/<name>/SKILL.md` (also discovered in parent dirs up to repo root, and lazily from nested subdirs once Claude touches files there), plugin `<plugin>/skills/<name>/SKILL.md` (namespaced `/plugin:skill`). Personal shadows project on name clash; skills shadow same-named `.claude/commands/` files; project skills can replace bundled skills. Live-reloaded on file change.
- Command name = directory name (`.claude/skills/deploy-staging/` → `/deploy-staging`); frontmatter `name` is display-only for personal/project skills, but sets the command's last segment for plugin skills.
- Frontmatter fields (all optional; `description` recommended): `name`, `description` (drives model auto-invocation; combined with `when_to_use`, truncated at 1,536 chars in the listing), `when_to_use`, `argument-hint`, `arguments` (named positional args), `disable-model-invocation: true` (only the user can invoke; description stays out of context — zero cost until invoked), `user-invocable: false` (only Claude can invoke), `allowed-tools` (tools pre-approved during the invoking turn; grant clears on your next message; NOT gated by workspace trust — audit repo skills before running), `disallowed-tools`, `model`, `effort`, `context: fork` (run in a forked subagent), `agent` (subagent type for fork), `background` (fork waits when `false`), `hooks`, `paths` (glob-scoped auto-activation), `shell` (`bash`|`powershell` for `!` lines), `metadata`, `license`, `compatibility`. Booleans accept `yes/no/on/off/1/0` (v2.1.218+).
- Substitutions in the body: `$ARGUMENTS` (full arg string; if absent, args are appended as `ARGUMENTS: <value>`), `$ARGUMENTS[N]` / `$N` (0-based, shell-style quoting), `$name` (from `arguments:` list), `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_SESSION_ID}`, plugin-only `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_DATA}`. `${CLAUDE_SKILL_DIR}` is also substituted in `allowed-tools` Bash rules, letting a skill pre-approve its own bundled script: `allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/render.sh *)`.
- Dynamic context: `` !`command` `` lines execute at invocation and inject output; `@path` references attach files. Invoked skill content enters the conversation once and persists for the session (permissions don't). After compaction, invoked skill bodies are re-injected capped at 5,000 tokens per skill / 25,000 total, oldest dropped first.
- Stacking: `/write-tests /fix-issue 123` loads both skills, passing `123` to each (v2.1.199+).
- Legacy commands: `.claude/commands/<name>.md` → `/name`; supports the same frontmatter except `name` and `paths`. Skills preferred (supporting files, invocation control).
- `-p` mode: `/skill-name args` inside the prompt string expands before the run. Skill listing (`/skills`) shows what's loaded; `disable-model-invocation: true` skills stay entirely out of context until invoked.

## Notable quotes

> "Custom commands have been merged into skills. A file at `.claude/commands/deploy.md` and a skill at `.claude/skills/deploy/SKILL.md` both create `/deploy`." — Skills guide

> "For security reasons, Claude Code prompts for approval in interactive sessions before using project-scoped servers from `.mcp.json` files." — MCP guide

> "A skill can grant itself broad tool access, so review the `allowed-tools` of skills checked into a repository before you run Claude Code there." — Skills guide

## Application to Ouroboros

The Generator writes `.mcp.json` (project scope, env-expanded secrets via `${VAR:-default}`) and `.claude/skills/` bundles into every harness repo; skills with `disable-model-invocation: true` + `allowed-tools` scoped to bundled scripts give deterministic, promptless operations the runner can trigger by embedding `/skill-name` in `-p` prompts. The runner must treat `.mcp.json` as an attack surface: `-p`/SDK sessions auto-connect project servers, so pair generated repos with `disabledMcpjsonServers`/`--setting-sources` policies, and set `MCP_TIMEOUT`, `MCP_TOOL_TIMEOUT`, and `MAX_MCP_OUTPUT_TOKENS` explicitly for long unattended sessions. The Inspector validates skill frontmatter against the field table and flags `allowed-tools` grants (not trust-gated) during repo audits.
