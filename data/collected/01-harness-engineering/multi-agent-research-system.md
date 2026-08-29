---
title: How we built our multi-agent research system
source_url: https://www.anthropic.com/engineering/multi-agent-research-system
publisher: Anthropic
retrieved: 2026-08-25
domain: harness-engineering
doc_type: engineering-blog
relevance: Production lessons on orchestrator-worker harnesses — effort scaling, delegation prompts, memory handoffs, checkpointing, rainbow deploys — that inform Ouroboros's multi-session and multi-agent runner design.
---

## Summary

Anthropic's writeup of the Claude Research feature describes an orchestrator-worker architecture: an Opus 4 lead agent plans and spawns parallel Sonnet 4 subagents that search with separate context windows, plus a CitationAgent for attribution. Multi-agent beat single-agent Opus by 90.2% on an internal research eval, largely because token spend is the dominant performance variable. The post distills eight prompt-engineering principles (notably explicit effort-scaling rules and detailed delegation), an evaluation strategy (start with ~20 queries, LLM-as-judge rubric, human spot checks, end-state evaluation), and production-engineering lessons (checkpoints, rainbow deployments, memory handoffs before context limits). It also candidly lists failure modes: 50 subagents for trivial queries, endless searching for nonexistent sources, and agents distracting each other.

## Key knowledge

### Architecture
- **LeadResearcher** (Opus 4): analyzes the query with extended thinking, plans strategy, spawns subagents, synthesizes.
- **Subagents** (Sonnet 4): 3–5 spawned in parallel; each calls 3+ tools in parallel; separate context windows; act as intelligent filters returning condensed findings. Interleaved thinking after tool results to evaluate quality, spot gaps, refine queries.
- **CitationAgent**: post-processes the report to attribute claims to sources.
- Lead saves its research plan to external memory before the context window truncates (>200k tokens), then retrieves it after reset — continuity through handoff, not through one giant context.
- Dynamic multi-step search, explicitly contrasted with static RAG retrieval.

### Why multi-agent wins (and when it doesn't)
- 90.2% improvement over single-agent Opus 4 on the internal research eval.
- On BrowseComp, three factors explain 95% of performance variance; **token usage alone explains 80%**; tool calls and model choice explain most of the rest. Multi-agent works mainly as a way to spend more tokens effectively via parallel separate contexts.
- Model upgrades beat budget increases: Sonnet 4 gains exceeded doubling the token budget on Sonnet 3.7.
- Cost reality: agents ≈ 4× chat tokens; multi-agent ≈ 15× chat tokens — only high-value tasks justify it.
- Good fit: parallelizable, breadth-first work exceeding one context window, many complex tools. Poor fit: tasks needing shared context or tight interdependencies — **including most coding work**, which is less parallelizable than research.
- Parallelism (3–5 subagents × 3+ parallel tool calls) cut research time by up to 90% for complex queries.

### Eight prompt-engineering principles
1. **Think like your agents** — build Console simulations with the exact prompts/tools and watch step-by-step to find failure modes (continuing past sufficient results, verbose queries, wrong tool choice).
2. **Teach the orchestrator to delegate** — every subagent task needs: objective, output format, tool/source guidance, and clear boundaries. Vague tasks ("research the semiconductor shortage") cause duplicated or divergent work.
3. **Scale effort to query complexity** — explicit rules in the prompt: simple fact-finding = 1 agent, 3–10 tool calls; direct comparisons = 2–4 subagents, 10–15 calls each; complex research = 10+ subagents with divided responsibilities. Without this, agents overinvest in trivial queries.
4. **Tool design is critical** — examine all tools first, match tool to intent, prefer specialized over generic; a bad description sends agents down completely wrong paths. MCP servers with variable-quality descriptions compound this.
5. **Let agents improve themselves** — a tool-testing agent repeatedly used flawed tools and rewrote their descriptions; future agents completed tasks **40% faster** with the rewritten descriptions.
6. **Start wide, then narrow** — default to short broad queries, evaluate the landscape, then drill down; agents default to overly long, specific queries that return little.
7. **Guide the thinking process** — extended thinking as a controllable, visible scratchpad for planning; interleaved thinking after tool results.
8. **Parallel tool calling** — spin up subagents and call tools concurrently, never serially.
- General posture: explicit guardrails to prevent runaway behavior; prompts encode research *heuristics* (from skilled humans) rather than rigid scripts; fast iteration loops with observability.

### Evaluation
- Start immediately with small samples (~20 representative queries); early effect sizes are huge (30% → 80% success from prompt tweaks), so small n suffices. Waiting for a large eval set is a named common mistake.
- **LLM-as-judge**: single call, single prompt, rubric → score 0.0–1.0 + pass/fail. Rubric dimensions: factual accuracy, citation accuracy, completeness, source quality, tool efficiency. Most consistent and human-aligned of the methods tried.
- **Human evaluation** still catches what automation misses — e.g. early agents preferred SEO content farms over authoritative sources; fixed with source-quality heuristics in prompts.
- **End-state evaluation** for state-mutating agents: judge the final state, not the path, since valid alternative paths exist; break long processes into discrete checkpoints with expected state changes.

### Production reliability
- Agents are stateful; minor tool failures cascade. Use durable execution with **checkpoints** to resume rather than restart from scratch; combine model adaptability (let the agent handle a failing tool) with deterministic safeguards (retry logic, regular checkpoints).
- Debugging: full production tracing of decision patterns and interaction structures (without surveilling content) to diagnose systematic failures — non-determinism makes ad hoc debugging useless.
- **Rainbow deployments**: shift traffic gradually while keeping old and new versions running, because updating a running agent mid-process breaks it.
- Sync vs async: current system is synchronous (lead waits on each subagent set) — simpler but bottlenecked by the slowest subagent; async promises more parallelism at the cost of coordination, state-consistency, and error-propagation complexity.
- **Artifact/filesystem pattern**: subagents write large outputs (code, reports, visualizations) directly to external storage and pass lightweight references to the coordinator — avoids the "game of telephone" loss and token overhead of copying outputs through conversation history.

### Failure modes catalog
- 50 subagents spawned for a simple query; endless web scouring for nonexistent sources; subagents distracting each other with excessive updates; searching the web for info that only existed in Slack; context truncation mid-task; cascading tool-failure errors.

## Notable quotes

> "Multi-agent systems work mainly because they help spend enough tokens to solve the problem." — Anthropic

> "We found that token usage by itself explains 80% of the variance." — Anthropic

## Application to Ouroboros

The **runner** borrows the memory-handoff pattern (persist the plan before context limits; resume from artifact, not summary), checkpointed durable execution, and the artifact/filesystem pattern (subagents write outputs to disk, pass references). The **Generator** should embed effort-scaling rules and delegation templates (objective, output format, tools, boundaries) into any generated multi-agent prompts — while heeding the warning that most coding work parallelizes poorly, so Ouroboros defaults to a single coder with research/review subagents. The **Inspector** adopts the eval strategy: ~20-task starter suites, an LLM-judge rubric scoring 0.0–1.0 with pass/fail, end-state (not path) checking, plus periodic human review for emergent failure modes like source-quality drift.
