---
title: Self-Improving Coding Agents
source_url: https://addyosmani.com/blog/self-improving-agents/
publisher: Addy Osmani (personal engineering blog)
retrieved: 2026-08-26
domain: harness-engineering
doc_type: engineering-blog
relevance: Practitioner blueprint for the exact loop Ouroboros generates — machine-readable backlog, atomic tasks, verify-then-commit cycle, and file-based memory that compounds across runs.
---

## Summary

Addy Osmani documents the practitioner pattern behind long-running autonomous coding loops (the "Ralph Wiggum technique"): a stateless-but-iterative loop that repeatedly picks the next task from a machine-readable backlog, implements it, validates with tests/type-checks/lint, commits only on green, logs learnings, and resets context. Persistence lives in four file channels — git history, a progress log, a task-state JSON, and an AGENTS.md knowledge file — so each iteration makes future iterations easier. The post covers atomic task design, feedback loops, scaling to concurrent agents via planner/worker/judge hierarchies, monitoring, stop conditions, and safeguards against destructive actions and hallucination.

## Key knowledge

### Backlog and atomic task design

- Backlog is a machine-readable task list, typically `prd.json`, holding granular user stories rather than monolithic features.
- An atomic task must (a) fit in one AI session and (b) have unambiguous pass/fail criteria. Bad: "Build dashboard." Good: "Add navigation bar with Home/About/Contact links; current page link highlighted blue."
- Explicit acceptance criteria shrink the space of acceptable solutions, which directly reduces hallucination risk.
- Every user story should have associated test coverage.

### The continuous loop

1. Pick next incomplete task from the backlog
2. Implement the feature/fix
3. Validate via tests, type checks, linting
4. Commit only if checks pass
5. Update task status and log learnings
6. Reset context and repeat

"Stateless but iterative": each run gets a fresh bounded prompt instead of one enormous accumulating prompt — this is the defense against context overflow and drift. Loop driver can be a trivial bash script, e.g.:

```
while :; do
  amp run -s prompt.md -o progress.txt
  if grep -q "<promise>COMPLETE</promise>" progress.txt; then break; fi
done
```

(pattern: sentinel token in output signals backlog completion).

### Four channels of persistent memory

1. **Git commit history** — agents read diffs/logs to see what changed; commit messages carry context.
2. **Progress log (`progress.txt`)** — chronological record per cycle: which task, pass/fail, errors hit.
3. **Task state (`prd.json`)** — completion status; prevents redoing work after restart.
4. **Semantic knowledge (`AGENTS.md`)** — accumulated conventions, gotchas ("Updating user model requires audit log update"), style preferences, recent learnings. Grows organically as the agent discovers patterns.

Context-injection hygiene: keep AGENTS.md focused and current, archive obsolete info separately; advanced setups retrieve only task-relevant sections to avoid bloat. Real-time correction technique: when a human catches an error, interrupt the loop and append the correction to AGENTS.md so the preference persists.

### Validation and QA

- Static analysis (TypeScript/MyPy type checks, ESLint/Flake8) runs before commit.
- For untestable UI work: headless-browser self-evaluation — agent spins up a browser, verifies element presence/interaction, reports pass/fail.
- Test-quality transfer (Simon Willison): agents mimic the test patterns they see, so maintaining high-quality tests in the repo is itself a control; reference good examples in prompts.
- Agent opens a PR rather than auto-merging; human reviews each morning, checking alignment with the *spirit* of the task, not just the letter of the acceptance criteria.

### Scaling to concurrent agents

- Naive parallelism fails: task conflicts, file-lock contention, and agents becoming risk-averse in a free-for-all.
- **Planner–worker–judge model**: planner agents read the codebase and spawn tasks (recursively); workers implement without owning strategy; a judge assesses completion. Cursor's team produced ~1M lines across 1,000+ files in a week this way.
- Practical middle ground: separate loops per area (front-end vs back-end, per feature branch) with clean work partitioning.
- Compound loops chain phases: Analysis loop → Planning loop (generates PRD + tasks) → Execution loop, letting agents decide *what* to build, not just *how*.

### Monitoring and stop conditions

- Tail `progress.txt` live; use `git log`/`git diff` as audit trail; quick status via `jq '.tasks[] | {id, story, passes}' prd.json`; track timing and token spend.
- Automated stop conditions: max iterations (e.g. 50), time limit (e.g. 3 hours), idle detection (no commit in last 5 iterations).
- If stuck, ask the agent to explain its reasoning — chain-of-thought output aids debugging.

### Safeguards

- Run on a feature branch, never main. Sandbox execution (Docker/VM). Minimally-scoped API tokens. Whitelist safe read-only ops (grep, git log, tests); require approval for writes (git push, rm).
- Hallucination mitigations: strong unambiguous specs; tests as tripwires; error-feedback loops for self-correction; periodic re-planning after major chunks to combat drift; optional cross-checking with a different model for planning vs coding.
- Context-bloat mitigations: summarize older progress (summaries of summaries); show only task-relevant code; lean on the model's trained knowledge for standard libraries.
- Economics: set budget alerts; reported ROI examples of ~$50k-scope projects for hundreds of dollars in API cost. Human role shifts from writing code to curating the process.

## Notable quotes

- "Each improvement should make future improvements easier." — Compound Product philosophy, quoted by Osmani
- "Once projects have clean tests, agents tend to match in quality." — Simon Willison, quoted by Osmani
- "Without checks, agents merrily introduce bugs while thinking they succeeded." — Addy Osmani

## Application to Ouroboros

- **Generator**: this is the reference shape for the generated harness — `prd.json` backlog with per-story pass/fail criteria, `progress.txt` cycle log, `AGENTS.md` learnings file, sentinel-token loop driver, and commit-only-on-green discipline baked into the loop prompt.
- **Runner**: adopt the stop conditions verbatim (max iterations, wall-clock limit, no-commit-in-N-iterations idle detection) and the fresh-context-per-iteration model; surface `progress.txt` tailing and the `jq` status one-liner as monitoring affordances.
- **Inspector**: the four memory channels are audit surfaces — diff git history against task state to detect claimed-but-unverified completions; the "spirit vs letter of acceptance criteria" review is an LLM-judge rubric.
- **Inquisitor**: enforce atomicity at intake — reject stories that can't fit one session or lack unambiguous pass/fail criteria; require at least one test per story.
