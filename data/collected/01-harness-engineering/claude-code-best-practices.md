---
title: Best practices for Claude Code (agentic coding)
source_url: https://code.claude.com/docs/en/best-practices
publisher: Anthropic
retrieved: 2026-08-25
domain: harness-engineering
doc_type: official-docs
relevance: The operational playbook for keeping a Claude Code session correct and on-spec — verification gates, CLAUDE.md tuning, context hygiene, headless fan-out — that Ouroboros repos must encode as defaults.
---

## Summary

Anthropic's Claude Code best-practices guide (successor to the original "Claude Code: best practices for agentic coding" engineering post; the old URL 308-redirects here) organizes everything around one constraint: the context window fills fast and performance degrades as it fills. Its top directive is to give Claude a check it can run — tests, builds, screenshots — escalating from in-prompt verification to `/goal` conditions, deterministic Stop hooks, and adversarial subagent review. It prescribes the explore → plan → implement → commit workflow, lean CLAUDE.md files, permission allowlists and sandboxing, aggressive context management (`/clear`, `/compact`, subagents), spec-writing via agent-led interviews, and headless `claude -p` automation with fan-out patterns and multi-session Writer/Reviewer setups.

## Key knowledge

### Governing constraint
- The context window holds every message, file read, and command output; LLM performance degrades as it fills — Claude starts "forgetting" earlier instructions. Context is "the most important resource to manage." Track usage with a custom status line and `/context`.

### Verification (the #1 practice)
- Without a runnable check, "looks done" is the agent's only stop signal and the human becomes the verification loop. Give Claude something that returns pass/fail: test suite, build exit code, linter, diff-against-fixture script, or browser screenshot vs design.
- Escalation ladder for how hard the check gates the stop:
  1. **In one prompt**: "run the tests after implementing" with example cases.
  2. **Across a session**: `/goal` condition — a separate evaluator re-checks after every turn until the goal resolves (Claude Code eventually stops a stalled run with the goal still set).
  3. **Deterministic gate**: a Stop hook runs the check as a script and blocks turn-end until it passes; Claude Code overrides the hook after **8 consecutive blocks**.
  4. **Second opinion**: verification subagent / dynamic workflow where a fresh model tries to refute the result — the agent doing the work isn't the one grading it.
- Demand evidence, not assertions: test output, the command run and its result, or a screenshot.
- Prompt patterns: give explicit test cases; "take a screenshot of the result and compare to the original, list differences and fix them"; "address the root cause, don't suppress the error."

### Explore → Plan → Implement → Commit
- Plan mode: `Shift+Tab` until `⏸ plan mode on`, or `claude --permission-mode plan`. Claude reads/answers without changing anything.
- `Ctrl+G` opens the plan in your editor for direct edits before proceeding.
- Skip planning for one-sentence-diff tasks; plan when scope is uncertain, multi-file, or unfamiliar.

### Prompt specificity
- Scope the task (file, scenario, testing preference); point to sources ("look through git history"); reference existing patterns ("HotDogWidget.php is a good example"); describe symptom + likely location + definition of fixed ("write a failing test that reproduces the issue, then fix it").
- Rich input: `@file` references, pasted images, URLs (allowlist domains via `/permissions`), `cat error.log | claude`, or let Claude fetch its own context.

### CLAUDE.md
- Read at the start of every conversation; generate a starter with `/init`; verify loading with `/context`.
- Include: bash commands Claude can't guess, non-default style rules, test instructions/runners, repo etiquette (branch naming, PR conventions), architecture decisions, env quirks, gotchas.
- Exclude: anything derivable from code, standard conventions, API docs, frequently changing info, file-by-file codebase descriptions, "write clean code" platitudes.
- Per-line test: "Would removing this cause Claude to make mistakes?" If not, cut. Bloated files cause instruction loss; if a rule keeps being ignored, the file is too long. Add "IMPORTANT" emphasis to at most the one critical line — emphasize everything and nothing stands out.
- Treat like code: check into git, prune regularly, test by observing behavior change; `/doctor` proposes cuts of derivable content. Imports via `@path/to/import` syntax.
- Only broadly-applicable content belongs in CLAUDE.md; occasional domain knowledge goes in skills (loaded on demand).

### Permissions, hooks, extensions
- Modes: auto mode (Pro/Max/Team default; classifier model reviews actions, blocks scope escalation/unknown infra/hostile-content actions) vs Manual (approve writes/Bash/MCP yourself). Cut prompts with `/permissions` allowlists (e.g. `npm run lint`, `git commit`) and `/sandbox` OS-level isolation.
- CLI tools (`gh`, `aws`, `gcloud`, `sentry-cli`) are the most context-efficient external integration; Claude can learn unknown CLIs via `foo-cli-tool --help`.
- MCP: `claude mcp add --transport http notion https://mcp.notion.com/mcp`.
- **Hooks are deterministic where CLAUDE.md is advisory** — use hooks for actions that must happen every time (e.g. "run eslint after every file edit", "block writes to the migrations folder"). Configure in `.claude/settings.json`; browse with `/hooks`; Claude can write them for you.
- Skills: `.claude/skills/<name>/SKILL.md` with `name`/`description` frontmatter; `disable-model-invocation: true` for side-effectful manual workflows; invoke as `/fix-issue 1234` with `$ARGUMENTS`.
- Subagents: `.claude/agents/<name>.md` with `name`, `description`, `tools`, `model` frontmatter — isolated context and restricted tool set.

### Spec-first communication
- For larger features: "Interview me in detail using the AskUserQuestion tool… then write a complete spec to SPEC.md." Then start a **fresh session** to execute the spec with clean context.
- Good specs are self-contained: name files and interfaces, state what's out of scope, end with an end-to-end verification step. "Time spent making the spec precise pays off more than time spent watching the implementation."

### Session and context management
- `Esc` stops mid-action (context preserved); `Esc Esc` / `/rewind` restores conversation and/or code state or summarizes from a checkpoint; "undo that"; `/clear` between unrelated tasks.
- Rule of thumb: after two failed corrections on the same issue, `/clear` and rewrite the prompt with what you learned — a clean session with a better prompt beats a long session of accumulated corrections.
- `/compact <instructions>` for steered compaction; customize survival rules in CLAUDE.md ("When compacting, always preserve the full list of modified files and any test commands"); `/btw` for side questions that shouldn't enter history.
- Subagents for investigation: exploration burns context, so delegate ("use subagents to investigate X") and receive summaries.
- Checkpoints: every prompt creates one; restores code and/or conversation — but only tracks Claude's file-edit tools, not Bash/external changes; not a git replacement. Enables deliberately risky attempts + rewind.
- Sessions persist: `claude --continue`, `claude --resume`, `/rename` (treat named sessions like branches, e.g. `oauth-migration`).

### Automation and scale
- Headless: `claude -p "prompt"`; `--output-format json` (single object with `result` field) or `--output-format stream-json --verbose` (one JSON object per line, starting with an init event); `--no-session-persistence` to skip saving. Pipe into pipelines: `claude -p "<prompt>" --output-format json | your_command`.
- Fan-out recipe: (1) have Claude write the target list to `files.txt`; (2) loop `claude -p "Migrate $file… Return OK or FAIL." --allowedTools "Edit,Bash(git commit *)"`; (3) test on 2–3 files, refine, then run at scale. `--allowedTools` scopes permissions for unattended runs. `/batch <instruction>` splits work across 5–30 subagents, each in its own worktree opening a PR.
- Autonomous runs: `claude --permission-mode auto -p "fix all lint errors"` — classifier reviews commands, doesn't halt non-interactive runs on repeated blocks.
- Parallel sessions: git worktrees, desktop app, cloud, `claude agents` (agent view), agent teams (experimental). Fresh contexts improve review: **Writer/Reviewer pattern** — session A implements, session B reviews the file for edge cases/race conditions, A addresses the feedback; or one Claude writes tests, another writes code to pass them.
- Adversarial review: subagent reviews the diff against PLAN.md in a fresh context — "Report gaps, not style preferences." Warning: a reviewer told to find gaps will always find some; chasing every finding causes over-engineering — restrict to correctness and stated requirements.

### Named failure patterns
- **Kitchen sink session** → `/clear` between unrelated tasks.
- **Correcting over and over** → after two failures, `/clear` + better prompt.
- **Over-specified CLAUDE.md** → prune ruthlessly; convert enforceable rules to hooks.
- **Trust-then-verify gap** → always provide verification; "If you can't verify it, don't ship it."
- **Infinite exploration** → scope investigations or push them into subagents.

## Notable quotes

> "Give Claude a check it can run: tests, a build, a screenshot to compare." — Anthropic docs

> "Bloated CLAUDE.md files cause Claude to ignore your actual instructions!" — Anthropic docs

> "A clean session with a better prompt almost always outperforms a long session with accumulated corrections." — Anthropic docs

## Application to Ouroboros

This page is effectively Ouroboros's default-settings spec. The **Generator** emits lean CLAUDE.md files passing the "would removing this cause mistakes?" test, converts must-happen rules into hooks (deterministic > advisory), pre-populates `/permissions` allowlists and sandbox config, and ships Stop-hook verification gates plus an adversarial-review subagent definition. The **Inquisitor** is the productized "interview me, write SPEC.md, execute in a fresh session" pattern. The **runner** uses headless `claude -p --output-format stream-json` with `--allowedTools` scoping, the fan-out loop for batch work, and the two-failed-corrections → reset heuristic. The **Inspector** enforces evidence-not-assertion (test output, screenshots) and the reviewer-scope rule (correctness gaps only, to avoid over-engineering drift).
