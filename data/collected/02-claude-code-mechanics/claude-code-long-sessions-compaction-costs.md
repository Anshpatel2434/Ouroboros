---
title: Long-session behavior — compaction, resume/continue, and cost tracking
source_url: https://code.claude.com/docs/en/context-window
publisher: Anthropic
retrieved: 2026-08-26
domain: claude-code-mechanics
doc_type: official-docs
relevance: Ouroboros drives multi-hour autonomous sessions — auto-compact thresholds, what survives summarization, session resume semantics, and cost telemetry are the physics its runner schedules around.
---

## Summary

In long sessions the context window fills with the system prompt, CLAUDE.md, auto memory, skill descriptions, and every tool result; Claude Code compacts automatically as the conversation approaches the model's limit, replacing history with a structured summary while re-injecting startup content, the plan, up to five recently-modified files, and invoked skill bodies. `/compact [instructions]` triggers it manually with focus guidance; `/autocompact <size>` / `--autocompact` / `CLAUDE_CODE_AUTO_COMPACT_WINDOW` set the threshold (100K–1M). Sessions persist as JSONL under `~/.claude/projects/<project>/<session-id>.jsonl` and are resumed with `claude --continue` (most recent), `claude --resume <id|name>` (works cross-project), or `/resume`; `--fork-session` branches. `/usage` reports per-session token/cost figures (computed locally at list rates) plus plan-limit bars and attribution; enterprise averages run ≈$13/dev/active day. Companion pages: code.claude.com/docs/en/sessions, /model-config, /costs.

## Key knowledge

### Context window and compaction
- `/context` shows a live breakdown of what's consuming context (CLAUDE.md, auto memory, MCP tool names, skill descriptions, files, hooks). `/memory` opens the memory files. Auto memory injects the first 200 lines or 25KB of MEMORY.md.
- `/compact [instructions]` replaces history with a summary, optionally focused (`/compact Focus on code samples and API usage`). In a fresh session it prints `Not enough messages to compact.` A `# Compact instructions` section in CLAUDE.md customizes summarization standing behavior. Compaction is itself a large request (it reads the whole conversation); `/clear` costs nothing.
- What survives compaction (per mechanism): system prompt/output style unchanged (outside message history); project-root CLAUDE.md, unscoped rules, auto memory, and the plan-mode plan are re-injected from disk; path-scoped rules and nested CLAUDE.md reload as matching files are re-read; up to five most-recently-modified files Claude read/edited are re-read (files >5,000 tokens come back as a path reference); invoked skill bodies are re-injected capped at 5,000 tokens/skill and 25,000 total (oldest dropped, truncation keeps the top of SKILL.md); hook-added context is summarized away; `SessionStart` hooks matching the `compact` source run and re-add their output. Skill *descriptions* are not re-injected.
- The summarization request inherits the session's extended-thinking configuration (v2.1.198+).
- Auto-compact threshold: by default compaction fires at the model's context limit; exceptions — Sonnet 4.6/Opus 4.6 without extended context compact at 200K; `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` forces native-1M models (Sonnet 5, Fable 5) to the 200K boundary; Sonnet 5 on the API auto-compacts around 967K by default; cloud sessions compact as they approach the limit.
- Setting the window (100K–1M; forms `200000`, `500k`, `1M`, or bare `100`–`1000` meaning thousands):
  - `/autocompact 500k` — saves `autoCompactWindow` to user settings; `/autocompact auto` restores the tuned default.
  - `claude --autocompact <size>` — one launch, overrides saved setting, not preempted by managed settings.
  - `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (plain token count only) — beats command, flag, and setting; for scripts/cloud.
  - Window is capped at the model's context window. `DISABLE_COMPACT` disables all compaction; `CLAUDE_CODE_MAX_CONTEXT_TOKENS` declares the real window for gateway/custom model IDs; `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1` defers to the API's too-long error.
- Partial compaction: `/rewind` → "Summarize from here" / "Summarize up to here". Pre-emptive tactics: `/clear` between unrelated tasks, delegate large reads to subagents (only the summary returns), `[1m]` model variants (`/model opus[1m]`, `claude-opus-4-8[1m]`) for a bigger window at standard pricing.

### Resume and continue
- Entry points: `claude --continue` (most recent interactive session in cwd; skips `-p`/SDK, background, and `/loop`-first sessions), `claude --resume` (interactive picker), `claude --resume <name-or-id>` (direct; searches current project + worktrees, then all projects, v2.1.223+), `claude --from-pr <number>`, in-session `/resume`. `claude -p --continue` includes `-p`/SDK/`/loop` sessions. `-p`/SDK sessions are resumable only by explicit session ID.
- Headless continuation: `claude -p --resume <session-id> "prompt" --output-format json | jq -r '.result'` — the standard scripted follow-up pattern.
- A resumed session restores: full history incl. tool calls, model (unless retired/disallowed/flag-overridden), `--agent` identity, permission mode (except `plan` and `bypassPermissions`, never restored; `auto` only if still eligible), active goal, unexpired scheduled tasks. NOT restored: `--mcp-config`, `--settings`, `--plugin-dir`, `--fallback-model`, `--add-dir` flags (pass again), mid-session `/add-dir`, background Bash/monitor tasks.
- `--fork-session` (with `--continue` or `--resume`) copies the conversation into a new session ID; in-session `/branch [name]` does the same and switches to it. Forked processes lose "allow for this session" grants.
- Resume from summary: Pro/Max, session idle >~1 h and >100K tokens → dialog offering "Resume from summary" (runs `/compact` immediately), "Resume full session as-is", "Don't ask me again".
- Naming: `claude -n <name>` at startup, `/rename` in session, Ctrl+R in the picker; named sessions resumable by name. Duplicate live names get a two-word suffix (v2.1.232+).
- Storage: JSONL transcripts at `~/.claude/projects/<project>/<session-id>.jsonl` (`<project>` = cwd path with non-alphanumerics → `-`; >200 chars truncated + hash). Format is internal and version-unstable — use `/export`, `--output-format json`, hooks' `transcript_path`, or the Agent SDK instead of parsing. Knobs: `CLAUDE_CONFIG_DIR` (move storage), `CLAUDE_CODE_PROJECT_DIR_NAME` (pin the project dir name, v2.1.234+, requires `CLAUDE_CONFIG_DIR`; 1-64 `[A-Za-z0-9_-]`), `cleanupPeriodDays` (settings, default 30-day retention), `CLAUDE_CODE_SKIP_PROMPT_HISTORY` (no transcript writes), `--no-session-persistence` (one `-p` run).
- Two terminals resuming the same session without forking interleave into one transcript.

### Cost and usage tracking
- `/usage`: Session block (total cost, API vs wall duration, lines changed, per-model input/output/cache tokens; dollar figure computed locally at list rates — authoritative billing is the Console usage page). Totals reset on `/clear` (v2.1.211+). Plan users also get usage bars, attribution (skills/subagents/plugins/MCP servers as % of usage), behavior flags (long context, cache misses at ≥10%), and heaviest-loop rows; `d`/`w` toggles 24 h vs 7 days.
- `/insights` writes an HTML working-patterns report to `~/.claude/usage-data/report.html` (up to 200 unseen sessions/run). `/usage-credits` manages overage credits. `/cost`-style JSON telemetry for scripts comes from `claude -p --output-format json` (`total_cost_usd`, per-model breakdown) or the SDK's `ResultMessage.total_cost_usd`.
- Benchmarks: ≈$13/developer/active day average, $150–250/dev/month, <$30/day for 90% of users. Team TPM sizing table: 1-5 users → 200k-300k TPM each, down to 10k-15k at 500+ users.
- Org-level: Teams/Enterprise spend report + Enterprise Analytics API (`read:analytics` scope); Console workspaces (auto-created "Claude Code" workspace) + Claude Code Analytics API; cloud providers → OpenTelemetry export (only near-real-time per-user stream), self-hosted gateway, or LiteLLM-style proxy.
- Why usage climbs while idle: full conversation re-sent every request (cached rate); cache lifetime 1 h on subscription / 5 min on API or usage credits — a longer break causes a full-context cache miss; scheduled tasks and cross-session messages fire with full context (`crossSessionInbound: hold` to stop inbound); goal check-ins (`CLAUDE_CODE_GOAL_CHECKIN_MINUTES=0` to disable); each active agent teammate keeps consuming (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` gate; ≈7x tokens in plan mode). Background overhead (resume summarization etc.) is typically under $0.04/session.
- Reduction levers: `/clear` between tasks; focused `/compact`; Sonnet/Haiku for routine work (`model: haiku` for subagents); MCP tool deferral + `/mcp` disable unused servers; prefer CLIs (`gh`, `aws`) over MCP; hooks that pre-filter output (PreToolUse `updatedInput` rewriting e.g. piping test output through `grep -A 5 FAIL | head -100`); move workflow text from CLAUDE.md (always loaded, keep <200 lines) into on-demand skills; lower `/effort` or `MAX_THINKING_TOKENS=8000` (fixed-budget models only); delegate verbose ops to subagents; plan mode + early Escape/`/rewind` to avoid wrong-path burn. SDK/CI caps: `max_budget_usd`, `max_turns`, `maxBudgetUsd`.

## Notable quotes

> "Claude Code compacts automatically as you approach the limit, so a full context window doesn't end your session." — Context window guide

> "Across enterprise deployments, the average cost is around $13 per developer per active day ... with costs remaining below $30 per active day for 90% of users." — Manage costs

> "Claude Code sends your full conversation with every request ... a one-line question in a session that has been open all day still draws usage for the whole conversation." — Manage costs

## Application to Ouroboros

The runner schedules long autonomous sessions around these mechanics: set `CLAUDE_CODE_AUTO_COMPACT_WINDOW` explicitly per harness, place must-survive invariants in project-root CLAUDE.md (re-injected after compaction) rather than hooks or path-scoped rules (summarized away), and register `SessionStart` hooks matching the `compact` source to re-arm guardrail context. Session continuity uses `claude -p --resume <session-id> --output-format json` between phases, with `--fork-session` for exploratory branches; the runner records `session_id` and `total_cost_usd` from each JSON result for its ledger. The Inspector taps `transcript_path` via hooks (never parses JSONL directly), and cost governance combines `max_budget_usd`/`max_turns` (SDK) with `/usage`-style telemetry and OpenTelemetry export for fleet dashboards.
