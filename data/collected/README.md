# Ouroboros Knowledge Corpus

Curated seed corpus for the Ouroboros meta-harness generator. 45 documents across
5 domains, each following the format in [CURATION_GUIDE.md](CURATION_GUIDE.md)
(frontmatter + Summary / Key knowledge / Notable quotes / Application to Ouroboros).
Machine-readable index: [MANIFEST.json](MANIFEST.json). Collected 2026-08-25/26.

## 01 — Harness Engineering (10 docs)

The Anthropic agent-engineering canon plus practitioner patterns for keeping
long-running coding agents on-spec.

| Document | What it contributes |
|---|---|
| building-effective-agents | Workflows-vs-agents taxonomy, five workflow patterns, agent loop design |
| effective-harnesses-for-long-running-agents | The canonical blueprint for the artifact Ouroboros generates: initializer/coder agents, feature lists, progress files |
| effective-context-engineering-for-ai-agents | Context as budgeted resource: compaction, memory files, just-in-time retrieval |
| claude-code-best-practices | Verification gates, CLAUDE.md tuning, headless fan-out defaults |
| writing-effective-tools-for-agents | Tool-surface design: consolidation, namespacing, token budgets |
| multi-agent-research-system | Production orchestrator-worker lessons: delegation, memory handoffs, checkpointing |
| spec-driven-development-with-spec-kit | specify → plan → tasks → implement pipeline with human checkpoints |
| self-improving-coding-agents | Stateless loop with machine-readable backlog, verify-then-commit, file memory |
| markdown-file-based-agent-memory | File-based memory architecture and the read-decide-act-update cycle |
| ai-coding-agent-security-guardrails | Deny-lists, sandboxing, env-scrubbing configs across five agent CLIs |

## 02 — Claude Code Mechanics (9 docs)

Everything needed to drive Claude Code programmatically in long unattended runs.

| Document | What it contributes |
|---|---|
| claude-code-cli-reference | Canonical flag/subcommand inventory |
| claude-code-headless-mode | `claude -p` recipes, output parsing, permission baselines |
| claude-agent-sdk-reference | Python/TS SDK: session APIs, options, resume, cost caps |
| claude-code-hooks-reference | PreToolUse/PostToolUse/Stop hooks — our deterministic guardrail layer |
| claude-md-memory-files | CLAUDE.md loading order, scoping, imports, size limits |
| claude-code-settings-permissions | settings.json precedence and allow/ask/deny rule grammar |
| claude-code-subagents-worktrees-parallelism | Subagents, concurrency limits, worktree isolation |
| claude-code-mcp-skills-commands | .mcp.json grammar, skill frontmatter, scope model |
| claude-code-long-sessions-compaction-costs | Auto-compact thresholds, resume semantics, cost telemetry |

## 03 — Orchestration / LangGraph (10 docs)

The framework substrate for the Inquisitor, Generator, and Slop Inspector graphs.

| Document | What it contributes |
|---|---|
| langgraph-graph-api-state-nodes-edges | StateGraph, reducers, conditional edges, Command |
| langgraph-persistence-checkpointing | Checkpointers, threads, resume across restarts |
| langgraph-interrupts-human-in-the-loop | interrupt()/Command(resume) — the Inquisitor's ask-and-wait loop |
| langgraph-structured-output-llm-nodes | Schema-enforced LLM output + validation retries — the verdict schema mechanism |
| langgraph-evaluator-optimizer-reflection-loops | Generate→judge→loop-until-pass pattern |
| langgraph-send-api-dynamic-fanout | Runtime map-reduce over commits/files/questions |
| langgraph-node-retry-policies-error-handling | RetryPolicy, TimeoutPolicy, fallback handlers |
| langgraph-streaming | Progress surfacing to CLI/dashboard |
| langgraph-subgraphs | Composing the three subsystems as subgraphs |
| langchain-multi-agent-architectures | Supervisor/handoff/router pattern taxonomy and tradeoffs |

## 04 — Evaluation & Slop Detection (8 docs)

The science behind the Slop Inspector's two-stage judgment.

| Document | What it contributes |
|---|---|
| anthropic-demystifying-evals-for-ai-agents | Grading agent behavior; grader stack design |
| evidently-llm-as-a-judge-guide | Judge prompt design, scoring modes, bias mitigation |
| codex-humaneval-pass-at-k | Functional-correctness evaluation and pass@k math |
| mutation-testing-code-generation-assessment | Why pass/fail on weak tests lies; mutation gates |
| sonarqube-quality-gates | Industry-standard deterministic quality-gate model |
| gitclear-2025-ai-code-quality-report-summary | Empirical shape of AI slop: duplication, churn, refactoring collapse |
| evilgenie-reward-hacking-benchmark | Reward-hacking taxonomy: test hardcoding, test-file edits |
| intent-drift-long-agent-sessions | Mechanisms and symptoms of goal drift in long sessions |

## 05 — Git & GitHub Integration (8 docs)

The PAT-only interception layer: detection, diffing, and write-back.

| Document | What it contributes |
|---|---|
| github-fine-grained-pats | Scopes, repo selection, expiration, limitations |
| github-rest-commits-compare | Commit detection and diff-pull endpoints |
| github-rest-write-operations | Issues, PRs, review comments, refs, statuses (check runs are App-only) |
| github-webhooks-push-and-polling | Push payloads, HMAC validation, ETag polling fallback |
| github-rest-rate-limits | Primary/secondary limits bounding polling and write throughput |
| github-actions-workflows | Triggers, secrets, GITHUB_TOKEN permissions, external calls |
| git-hooks-mechanics | Hook lifecycle, core.hooksPath, distribution strategies |
| git-worktrees-branch-protection | Parallel checkouts for agent fleets; protected-branch constraints |

## Known constraints surfaced during collection

- **Check runs require a GitHub App** — in PAT-only v1 the Inspector reports via
  commit statuses, issues, and PR comments instead.
- Git hooks do not clone with a repo — generated harnesses must wire them via
  `core.hooksPath` or an install step in `init.sh`.
