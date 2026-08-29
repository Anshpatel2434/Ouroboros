---
title: Subagents and parallel sessions with git worktrees
source_url: https://code.claude.com/docs/en/sub-agents
publisher: Anthropic
retrieved: 2026-08-26
domain: claude-code-mechanics
doc_type: official-docs
relevance: Ouroboros orchestrates parallel autonomous work — subagent definitions, concurrency/depth limits, and worktree isolation are the native primitives for fan-out without file collisions.
---

## Summary

Subagents are specialized assistants defined as Markdown files with YAML frontmatter that run in isolated context windows with their own system prompt, tool allowlist, model, and permission mode. Claude delegates to them via the `Agent` tool; they can run foreground or background, be resumed with `SendMessage`, persist memory, and be capped by concurrency (default 20) and nesting depth (default 3). Git worktrees are the file-isolation counterpart: `claude --worktree <name>` starts a session in `.claude/worktrees/<name>/` on branch `worktree-<name>`, and `isolation: worktree` in a subagent's frontmatter gives each subagent its own checkout so parallel edits never collide. Claude Code enforces worktree isolation by blocking tool calls that would touch the main checkout. Companion page: code.claude.com/docs/en/worktrees.

## Key knowledge

### Subagent definition and discovery
- Locations by priority: managed settings (1) > `--agents` CLI JSON (2) > project `.claude/agents/` (3) > user `~/.claude/agents/` (4) > plugin `agents/` (5). Directories scanned recursively; identity comes from the `name` field only. Nested duplicates: closest to cwd wins (v2.1.178+).
- Required frontmatter: `name` (lowercase + hyphens, no colons), `description` (Claude uses it to decide when to delegate). Markdown body = system prompt.
- Optional frontmatter: `tools` (allowlist, e.g. `Read, Grep, Glob, Bash`), `disallowedTools`, `model` (`sonnet`/`opus`/`haiku`/`fable`/full ID/`inherit`), `permissionMode` (`default|acceptEdits|auto|dontAsk|bypassPermissions|plan`), `maxTurns`, `skills` (preloaded full content), `mcpServers`, `hooks` (PreToolUse/PostToolUse/Stop; Stop becomes SubagentStop), `memory` (`user` → `~/.claude/agent-memory/<name>/`, `project` → `.claude/agent-memory/<name>/`, `local`), `background: true`, `effort` (`low|medium|high|xhigh|max`), `isolation: worktree`, `color`, `initialPrompt`.
- `tools: Agent(worker, researcher)` restricts which subagents this one may spawn; bare `Agent` allows any.
- Validate definitions: `claude plugin validate .claude/agents/`.

### Built-in subagents
- `Explore`: read-only (Read, Grep, Glob, WebFetch, WebSearch), skips CLAUDE.md and git status, thoroughness levels `quick`/`medium`/`very thorough`. `Plan`: read-only research for plan mode. `general-purpose`: all tools. Also `claude` (fallback), `statusline-setup`, `claude-code-guide` (Haiku).
- Disable: `"permissions": {"deny": ["Agent(Explore)"]}` or `--disallowedTools "Agent(Explore)"`; env `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` or `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` (SDK/non-interactive).

### Invocation
- Natural language, `@agent-<name>` mention (guaranteed delegation), session-wide `claude --agent code-reviewer` (or `"agent"` settings key), or define inline: `claude --agents '{"code-reviewer": {"description": "...", "prompt": "...", "tools": ["Read","Grep"], "model": "sonnet"}}'`.
- Model resolution order: `CLAUDE_CODE_SUBAGENT_MODEL` env > per-invocation `model` param > frontmatter `model` > main conversation model.
- Resume a finished/stopped subagent with the `SendMessage` tool (`{"to": "<name-or-id>", "message": "..."}`); transcripts persist at `~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`, survive compaction, auto-clean after `cleanupPeriodDays` (default 30).
- Forked subagents (`/subtask <task>`, v2.1.212+) inherit full history, tools, model, and prompt cache; skip tool filters.

### Limits and background behavior
- Concurrency: default 20 simultaneous subagents; overflow errors "Concurrent subagent limit reached"; configure with `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (v2.1.217+).
- Depth: default 3 layers; configure `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (1 disables nesting). At the limit the `Agent` tool is withheld (forks exempt).
- Background subagents get a reduced built-in tool set (keep Read/Grep/Glob/Bash/PowerShell/Edit/Write/NotebookEdit/WebFetch/WebSearch/TodoWrite/Skill/ToolSearch/EnterWorktree/ExitWorktree/Monitor/TaskStop/SendMessage/Artifact + all MCP tools). Removed from all subagents: `AskUserQuestion`, `EndConversation`, plan-mode tools, etc. `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` forces foreground.
- Permission override rules: parent's `bypassPermissions`/`acceptEdits` take precedence; parent in auto mode forces subagent auto. `permissions.disableBypassPermissionsMode` makes frontmatter `bypassPermissions` ignored (v2.1.223+).
- Context loaded at subagent start: system prompt, task message, CLAUDE.md hierarchy (except Explore/Plan), git snapshot, preloaded skills, sibling roster. NOT passed: output styles, main session auto memory, skill invocation history.

### Worktrees — `--worktree` / `-w`
- `claude --worktree feature-auth` creates `.claude/worktrees/feature-auth/` at repo root on new branch `worktree-feature-auth`; omitting the name generates one (e.g. `bright-running-fox`). Add `.claude/worktrees/` to `.gitignore`.
- Interactive `--worktree` requires prior workspace trust; `claude -p --worktree` skips the trust check.
- Cleanup on interactive exit: clean+unnamed → auto-removed; dirty or named → prompt to keep/remove. `-p` runs never clean up (use `git worktree remove`, `git worktree unlock` if locked).
- Resume returns the session to its worktree (interactive, `-p --continue/--resume`, and SDK; v2.1.212+ for non-interactive). Non-interactive resumes abort with stderr errors if the worktree fails verification; a deleted worktree resumes in the launch directory with the binding cleared.
- Isolation enforcement (4 checks, not disableable): blocks Edit/Write/NotebookEdit targeting the main checkout; blocks commands whose cwd resolves to the main checkout; blocks git redirects into it (`git -C`, `--git-dir`, `GIT_DIR`, `GIT_WORK_TREE`, `cd`); blocks unverifiable shell constructs (brace expansion, unquoted heredocs).
- Subagent worktrees: ask Claude to "use worktrees for your agents" or set `isolation: worktree` frontmatter. Temporary worktree removed automatically when the subagent finishes with no changes; dirty ones kept until the periodic sweep (respects `cleanupPeriodDays`, skips worktrees holding work, releases locks of dead sessions). `git worktree lock` is held while an agent runs.
- `worktree.baseRef` setting: `"fresh"` (default; branch from remote default branch, fetch capped at 5s if stale >24h) or `"head"` (branch from local HEAD, carrying unpushed work). No branch names accepted — use `git worktree add` manually for that.
- `--worktree "#1234"` or a PR/MR URL branches from the PR head into `.claude/worktrees/pr-<number>` (fetches `pull/<n>/head` on GitHub, `merge-requests/<n>/head` on GitLab).
- `.worktreeinclude` file at project root (gitignore syntax) copies matching *gitignored* files (e.g. `.env`, `config/secrets.json`) into every worktree Claude creates.
- Reusing a name reopens the existing worktree; with `"fresh"` base a clean, merged worktree resets to the default branch.
- Shared with the main checkout: the `.git` directory, project-scope plugins, and saved permission approvals (`settings.local.json` lives at the main checkout root, v2.1.211+; Windows keeps it in the starting directory).
- Manual parallel pattern: `git worktree add ../project-feature-a -b feature-a`, then `cd ../project-feature-a && claude` per terminal; `git worktree list` / `git worktree remove` to manage.
- Non-git VCS: replace creation/cleanup with `WorktreeCreate` / `WorktreeRemove` hooks (hook prints the created directory path on stdout; `.worktreeinclude` is not processed).
- Hook path caveat: after entering a worktree, `${CLAUDE_PROJECT_DIR}` still points at the original project root; the hook input JSON's `cwd` field carries the worktree path.
- Permission rules can gate parameters: `Agent(isolation:worktree)`, `Agent(model:opus)` as deny/ask rules.

## Notable quotes

> "Running each Claude Code session in its own worktree means edits in one session never touch files in another." — Worktrees guide

> "Subagents ... run in isolated context windows with custom system prompts, specific tool access, and independent permissions." — Subagents reference

> "Each subagent gets a temporary worktree that Claude Code removes automatically when the subagent finishes without changes." — Worktrees guide

## Application to Ouroboros

The Generator should emit `.claude/agents/*.md` definitions with pinned `tools`, `model`, `maxTurns`, and `permissionMode` per role, plus `isolation: worktree` for any write-heavy agent, and a `.worktreeinclude` carrying `.env`-style files into checkouts. The runner uses `claude -p --worktree <name>` (or SDK `agents` + `isolation`) for parallel task fan-out, budgeting against the 20-concurrent/3-deep limits via `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` / `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, and must handle `-p` worktrees never self-cleaning (schedule `git worktree remove` in teardown). The Inspector can rely on Claude Code's own isolation enforcement as a hard floor and audit subagent transcripts under `~/.claude/projects/{project}/{sessionId}/subagents/`.
