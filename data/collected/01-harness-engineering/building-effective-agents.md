---
title: Building effective agents
source_url: https://www.anthropic.com/engineering/building-effective-agents
publisher: Anthropic
retrieved: 2026-08-25
domain: harness-engineering
doc_type: engineering-blog
relevance: Foundational taxonomy (workflows vs agents, five workflow patterns, agent loop, ACI design) that Ouroboros uses to decide how much autonomy vs fixed orchestration a generated harness should encode.
---

## Summary

Anthropic's December 2024 foundational post distinguishes *workflows* (LLMs and tools orchestrated through predefined code paths) from *agents* (the LLM dynamically directs its own process and tool use), and catalogs five composable workflow patterns plus the autonomous agent loop. Its central thesis is simplicity: start with a single optimized LLM call, escalate to workflows only when that fails, and to agents only when open-ended flexibility is genuinely required, because autonomy brings higher cost and compounding error. It also argues that agent-computer interface (ACI) design deserves as much investment as human-computer interface design, and identifies coding as an ideal agent domain because solutions are automatically verifiable via tests.

## Key knowledge

### Definitions
- **Agentic systems**: umbrella term for both workflows and agents.
- **Workflows**: orchestration is programmatically controlled through predefined code paths.
- **Agents**: the model maintains control over how it accomplishes the task, dynamically choosing tools and steps.

### Five workflow patterns
1. **Prompt chaining** — decompose into sequential steps, each call consuming the previous output, with programmatic gates/checks between steps. Use when the task decomposes cleanly into fixed subtasks and you trade latency for accuracy. Examples: generate copy → translate; write outline → validate → write document.
2. **Routing** — classify the input, dispatch to a specialized downstream prompt/handler. Enables separation of concerns and per-category prompt optimization. Examples: customer-service triage (general/refund/technical); cost routing (easy queries → Haiku, hard → Sonnet).
3. **Parallelization** — two flavors:
   - *Sectioning*: split into independent subtasks run in parallel (e.g., guardrail model screening input while another handles the response; automated evals scoring different aspects).
   - *Voting*: run the same task multiple times for diverse outputs (e.g., several prompts review code for vulnerabilities; content flagged if any/threshold votes agree).
4. **Orchestrator-workers** — a central LLM dynamically decomposes the task, delegates to worker LLMs, and synthesizes results. Differs from parallelization because subtasks are not predictable in advance. Examples: multi-file code changes; multi-source research.
5. **Evaluator-optimizer** — one LLM generates, another evaluates and gives feedback in a loop. Use when there are clear evaluation criteria and iteration measurably helps — analogous to a human writer's revision loop. Examples: literary translation; multi-round search analysis.

### The agent loop
- Starts with a command from, or interactive discussion with, the human user; once the task is clear the agent plans and operates autonomously.
- At each step it must obtain **ground truth from the environment** (tool results, code execution) to assess progress — this environmental feedback is what keeps the loop honest.
- Can pause for human feedback at checkpoints or when blocked.
- Terminates on completion or on a **stopping condition such as a maximum number of iterations** to retain control.
- Implementation is typically simple: an LLM using tools in a loop based on feedback; the sophistication lives in the tools, prompts, and environment.

### When workflows vs agents
- Workflows: predictable, well-defined tasks; lower cost/latency; controlled complexity.
- Agents: open-ended problems where the number of steps is unpredictable and a fixed path cannot be hardcoded; higher cost and compounding-error risk.
- Escalation ladder: optimized single call with retrieval/examples → workflow → agent. Only add complexity when it demonstrably improves outcomes.

### Guardrails and safety
- Set max-iteration limits as stopping conditions.
- Test extensively in sandboxed environments before production.
- Add human checkpoints for verification.
- Autonomy explicitly means "higher costs, and the potential for compounding errors."

### Framework guidance
- Start with LLM APIs directly; many patterns are a few lines of code. Frameworks (Claude Agent SDK, Rivet, Vellum, etc.) speed startup but add abstraction layers that obscure prompts/responses, complicate debugging, and tempt over-engineering. If you use one, understand the underlying code.

### Tool / ACI design (appendix)
- Invest in agent-computer interfaces as heavily as HCI.
- Give the model enough tokens to "think" before it commits itself into a corner.
- Keep tool formats close to what the model has seen in natural internet text; avoid formatting overhead like accurate line counting or heavy string escaping.
- Docstring test: would a junior developer need careful study to use this tool correctly? If so, rewrite the description — include example usage, edge cases, input format requirements, and boundaries with other tools.
- Poka-yoke the arguments: change parameter shapes so mistakes become impossible (e.g., require absolute filepaths, because relative paths break after the agent `cd`s).
- Empirical note: the SWE-bench agent effort spent more time optimizing tools than the overall prompt.

### Coding as an agent domain (appendix)
- Coding is ideal because solutions are verifiable via automated tests and the agent can iterate on test feedback; agents solved real GitHub issues on SWE-bench Verified from PR descriptions alone.
- Caveat: passing tests verify functionality but not system-wide alignment — human review remains essential.
- Customer support is the other flagship domain (conversation + tools + programmatic actions + clear success metrics; some vendors charge per successful resolution).

### Three core principles
1. **Simplicity** in design; add steps only when they demonstrably pay.
2. **Transparency** — explicitly show the agent's planning steps.
3. **Craft the ACI** — thorough tool documentation and testing.

## Notable quotes

> "Success in the LLM space isn't about building the most sophisticated system." — Anthropic

> "Frameworks can help you get started quickly, but don't hesitate to reduce abstraction layers." — Anthropic

## Application to Ouroboros

The **Generator** should treat this taxonomy as its decision table: encode fixed, predictable phases of a generated repo's lifecycle (spec → plan → scaffold → verify) as workflow steps with programmatic gates, and reserve agent-style autonomy for the open-ended coding sessions — always with max-iteration stopping conditions and sandboxing baked into the generated config. The **Inspector** is an instance of the evaluator-optimizer and parallelization/voting patterns (independent judges over the same diff). The **runner** implements the agent loop with ground-truth environmental feedback (tests, builds) as the progress signal, and the ACI checklist (poka-yoke parameters, absolute paths, junior-developer docstring test) governs any tools Ouroboros injects into generated harnesses.
