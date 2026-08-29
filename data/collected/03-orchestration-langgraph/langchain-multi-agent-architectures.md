---
title: Multi-Agent Architectures — Subagents, Handoffs, Skills, Routers, Custom Workflows
source_url: https://docs.langchain.com/oss/python/langchain/multi-agent
publisher: LangChain
retrieved: 2026-08-25
domain: orchestration-langgraph
doc_type: official-docs
relevance: Ouroboros is itself a multi-agent product; this page's pattern taxonomy and call-count/token tradeoffs drive how the three subsystems compose.
---

## Summary

LangChain's multi-agent guide catalogs five architectures for splitting work
across agents: subagents (a coordinator calls specialist agents as tools — the
supervisor pattern), handoffs (agents transfer control to each other via tool
calls, keeping conversational state), skills (one agent loads specialized
prompts/knowledge on demand), routers (a classification step dispatches to
specialists and synthesizes results), and fully custom LangGraph workflows that
mix deterministic logic with agentic nodes. Each pattern trades off model-call
count, token usage, parallelizability, and statefulness; context engineering —
deciding what each agent sees — is named the central design concern.

## Key knowledge

- Subagents (supervisor pattern): a main agent coordinates specialized agents exposed as callable tools; all routing decisions pass through the central coordinator. Cost profile: ~4 model calls for a single task, ~8 for repeated requests (the coordinator adds a call each hop). Strengths: parallelization, context isolation (subagent contexts don't bloat the coordinator), distributed team ownership. Weakness: extra model-call overhead.
- Handoffs: "agents transfer control to each other via tool calls"; conversational context is maintained across the transfer, and the currently-active agent talks directly to the user. Cost: ~3 calls initially, ~2 on repeat requests because state persists (stateful design saves 40–50% of calls). Weakness: strictly sequential — cannot parallelize.
- Skills: a single agent loads specialized prompts and knowledge on demand; context accumulates in one conversation history. Cost: ~3 calls initially, 2 on repeats, but token usage grows with loaded contexts (~15K tokens on multi-domain tasks in the docs' benchmark). Strengths: fewest moving parts, direct user interaction.
- Router: a dedicated routing step classifies the input, dispatches to one or more specialized agents (parallelizable), and results are synthesized into a combined response. Cost: ~3 initial calls; ~9K tokens on multi-domain tasks. Weakness: stateless — pays an LLM routing call on every request.
- Custom workflow: build the topology directly in LangGraph; mix deterministic logic with agentic behavior, and embed any of the other patterns as nodes. This is the escape hatch when the packaged patterns don't fit.
- Selection heuristics from the docs' comparison:
  - Single sequential tasks → handoffs / skills / router (3 calls each).
  - Repeat requests in an ongoing session → handoffs or skills (statefulness pays off).
  - Multi-domain or latency-sensitive → subagents or router (parallel execution).
  - Large per-domain contexts → subagents or router (isolation prevents context bloat).
- Central design principle: context engineering — deciding what information each agent sees — is what makes or breaks a multi-agent design; isolation is a feature, not a limitation.

## Notable quotes

> "Agents transfer control to each other via tool calls." — LangChain docs, on handoffs

> "Deciding what information each agent sees is central to multi-agent design success." — LangChain docs

## Application to Ouroboros

The Ouroboros runner is effectively a supervisor over three specialist graphs
(Inquisitor, Generator, Slop Inspector) — the subagents pattern, chosen for
context isolation: the Inspector must never see the Inquisitor's raw interview
transcript, only the distilled spec. The Inquisitor→Generator transition is a
handoff (spec travels, interview context is dropped). The Inspector internally
is closer to a router: a cheap classification step decides which judge
specialists (style, security, drift) to fan out to, then synthesizes a verdict —
worth it because judges can run in parallel per commit.
