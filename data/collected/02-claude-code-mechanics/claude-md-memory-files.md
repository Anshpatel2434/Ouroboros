---
title: CLAUDE.md and memory files (loading, scoping, imports, auto memory)
source_url: https://code.claude.com/docs/en/memory
publisher: Anthropic
retrieved: 2026-08-25
domain: claude-code-mechanics
doc_type: official-docs
relevance: Ouroboros's Generator writes CLAUDE.md/rules into every harness repo; loading order, size limits, and compaction survival determine what instructions actually reach the agent.
---

## Summary

Explains Claude Code's two cross-session memory mechanisms: human-authored CLAUDE.md instruction files and Claude-written auto memory. Details every CLAUDE.md location and scope (managed policy, user, project, local), the recursive load order, `@path` import syntax, `.claude/rules/` with path-scoped frontmatter, size limits and adherence guidance, `claudeMdExcludes`, and auto memory's storage layout (`MEMORY.md` index, 200-line/25KB load cap). Emphasizes that CLAUDE.md is context, not enforcement — hooks are the enforcement layer.

## Key knowledge

### Locations and scopes (load order, broadest first)
- **Managed policy**: macOS `/Library/Application Support/ClaudeCode/CLAUDE.md`; Linux/WSL `/etc/claude-code/CLAUDE.md`; Windows `C:\Program Files\ClaudeCode\CLAUDE.md`. Cannot be excluded by users. Alternatively the `claudeMd` key in `managed-settings.json` carries content inline (honored only in managed/policy settings).
- **User**: `~/.claude/CLAUDE.md` — all projects.
- **Project**: `./CLAUDE.md` or `./.claude/CLAUDE.md` — team-shared via VCS.
- **Local**: `./CLAUDE.local.md` — personal, gitignore it; appended after CLAUDE.md at the same level.

### Loading behavior
- Claude Code loads `CLAUDE.md`/`CLAUDE.local.md` from cwd and **every directory above it**; all files are concatenated (never overriding), ordered from filesystem root down to cwd, so the closest file is read last.
- Files in **subdirectories** below cwd load on demand when Claude reads files in those directories.
- Content is delivered as a user message after the system prompt, not in the system prompt itself — no strict compliance guarantee. For system-prompt-level instructions use `--append-system-prompt`.
- Block-level HTML comments (`<!-- ... -->`) are stripped before injection (comments in code blocks preserved).
- A CLAUDE.md up to 4 MiB loads in full; larger files are skipped. Target **under 200 lines** per file for adherence.
- Verify what loaded: `/context` (lists Memory files); edit via `/memory`; `/init` generates a starter CLAUDE.md (with `CLAUDE_CODE_NEW_INIT=1` an interactive multi-phase flow that also reads `AGENTS.md`, Cursor/Copilot/Windsurf/Cline rules).
- `--add-dir` directories do NOT load CLAUDE.md by default; set `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` to load `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/*.md`, `CLAUDE.local.md` from them.

### Imports
- `@path/to/import` syntax anywhere in a CLAUDE.md; relative paths resolve relative to the importing file; recursive imports max depth 4 hops. Imported files load at launch (imports organize but don't save context).
- Import parsing skips code spans/fenced blocks — wrap `` `@README` `` in backticks to mention without importing.
- `@AGENTS.md` as first line is the recommended interop pattern (or `ln -s AGENTS.md CLAUDE.md`; symlink needs admin/Developer Mode on Windows).
- External imports (resolving outside the working directory) in project-level files trigger a one-time approval dialog; user-scope files' imports are trusted without a dialog (except Cowork desktop sessions).
- Cross-worktree personal instructions: `@~/.claude/my-project-instructions.md`.

### `.claude/rules/` (modular instructions)
- Markdown files in `.claude/rules/` (discovered recursively; subdirectories allowed). Rules without `paths` frontmatter load at launch with same priority as `.claude/CLAUDE.md`.
- Path-scoped rules:
```markdown
---
paths:
  - "src/api/**/*.ts"
  - "src/**/*.{ts,tsx}"
---
```
  Load only when Claude reads/works with matching files. Glob patterns: `**/*.ts`, `src/**/*`, `*.md`, brace expansion (budget: 1,000 expanded patterns / 4 MiB per rule's `paths` list). Escape literal `[` as `\[`.
- User-level rules: `~/.claude/rules/` — loaded before project rules (project wins). Symlinks supported (shared rule sets), circular symlinks handled.
- Rules are skipped if `project` excluded from `--setting-sources` (v2.1.211+ fully).

### Exclusions
- `claudeMdExcludes` setting (any settings layer; arrays merge): glob patterns matched against absolute paths, e.g.
```json
{"claudeMdExcludes": ["**/monorepo/CLAUDE.md", "/home/user/monorepo/other-team/.claude/rules/**"]}
```
  Managed policy CLAUDE.md cannot be excluded.

### Auto memory
- Claude-authored notes, on by default; toggle `autoMemoryEnabled` (user or project settings) or `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.
- Storage: `~/.claude/projects/<project>/memory/` (project derived from git repo; all worktrees share it). Override location with `autoMemoryDirectory` setting (absolute or `~/` path).
- Layout: `MEMORY.md` index + topic files (`user_role.md`, `feedback_testing.md`, ...). First **200 lines or 25KB** of MEMORY.md load at session start; topic files read on demand. Note types recorded in frontmatter `type`: `user`, `feedback`, `project`, `reference`.
- Memory files are exempt from the `cleanupPeriodDays` transcript retention sweep. Writes get `modified` ISO-8601 frontmatter timestamps (v2.1.214+).
- Subagent auto memory is separate (subagent `memory` field); main-session auto memory is not loaded into subagents (except forks).

### Compaction interaction
- Project-root CLAUDE.md survives `/compact` (re-read from disk and re-injected). Nested CLAUDE.md and path-scoped rules reload only as Claude re-reads matching files. Conversation-only instructions are lost — persist them in CLAUDE.md.

### CLAUDE.md vs enforcement
- CLAUDE.md and auto memory are context, not enforced configuration. To block actions regardless of model behavior: `permissions.deny` and PreToolUse hooks. Managed settings for technical enforcement; managed CLAUDE.md for behavioral guidance.

## Notable quotes

> "CLAUDE.md content is delivered as a user message after the system prompt, not as part of the system prompt itself."

> "Settings rules are enforced by the client regardless of what Claude decides to do. CLAUDE.md instructions ... are not a hard enforcement layer."

## Application to Ouroboros

The Generator should emit: a project CLAUDE.md under 200 lines with concrete, verifiable rules (build/test commands, loop protocol); `.claude/rules/*.md` with `paths:` frontmatter for area-specific constraints so context isn't wasted; and rely on hooks — never CLAUDE.md — for hard guarantees. Because only the project-root CLAUDE.md survives compaction automatically, harness-critical loop instructions must live there (or be re-injected via a SessionStart `compact` hook), not in nested files. The runner should treat `/context` output and the 4 MiB/200-line limits as validation checks (Inspector lint: flag oversized CLAUDE.md). Auto memory should typically be disabled (`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` or `--bare`) in reproducible unattended runs so behavior doesn't drift across sessions.
