---
title: Effective context engineering for AI agents
source_url: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
publisher: Anthropic
retrieved: 2026-08-25
domain: harness-engineering
doc_type: engineering-blog
relevance: Defines context as the scarce resource a harness must budget — compaction, memory files, sub-agents, just-in-time retrieval — which directly shapes how Ouroboros repos keep long sessions from drifting.
---

## Summary

This Anthropic post reframes prompt engineering as a subset of *context engineering*: curating the optimal set of tokens (system prompt, tools, message history, retrieved data) at every inference step, because context is a finite resource that degrades with size ("context rot"). It gives concrete guidance for system-prompt "altitude", minimal tool sets, curated few-shot examples, and just-in-time retrieval, then presents three techniques for long-horizon work — compaction, structured note-taking (memory files), and sub-agent architectures — with criteria for choosing among them. It is the theoretical underpinning for why harnesses use NOTES.md-style state files and fresh contexts instead of ever-growing conversations.

## Key knowledge

### Definitions and the attention budget
- **Context engineering**: strategies for curating and maintaining the optimal set of tokens during inference — system instructions, tools, MCP, external data, message history — re-decided every turn. **Prompt engineering** covers only writing the instructions.
- **Context rot**: as token count grows, per-token recall accuracy falls (needle-in-a-haystack results); all models exhibit it to differing degrees.
- Architectural cause: transformer attention forms n² pairwise relationships; long contexts stretch this thin, and models saw mostly shorter sequences in training. Position-encoding interpolation helps but degrades positional precision. Models remain capable at long context but lose retrieval precision and long-range reasoning.
- Consequence: every token spends attention budget; the goal is the smallest set of high-signal tokens that maximizes the probability of the desired outcome.

### System prompt: the "right altitude"
- Two failure extremes: (a) hardcoded brittle if-else prompt logic (fragile, high maintenance); (b) vague high-level guidance that assumes shared context the model lacks.
- Target: specific enough to steer, flexible enough to act as heuristics — the *minimal set of information that fully outlines expected behavior* (minimal ≠ short).
- Organize with distinct sections (`<background_information>`, `<instructions>`, `## Tool guidance`, `## Output description`) using XML tags or Markdown headers.
- Method: start with a minimal prompt on the best model, then add instructions only in response to observed failure modes.

### Tools
- Tools are the contract between the agent and its information/action space; they must be token-efficient, self-contained, error-robust, and unambiguous in intended use.
- Failure mode: bloated tool sets with overlapping functionality. Heuristic: if a human engineer can't say definitively which tool applies, the agent can't either. Prefer a minimal viable tool set.

### Few-shot examples
- Still strongly advised, but curate a few diverse, canonical examples rather than stuffing a laundry list of edge cases into the prompt.

### Retrieval strategy
- **Just-in-time retrieval**: keep lightweight identifiers (file paths, queries, links) in context and load data at runtime via tools — mirrors human use of external organization systems. Metadata (file names, folder hierarchy, timestamps) itself signals behavior. Enables *progressive disclosure* — incremental discovery through exploration.
- Claude Code's implementation: CLAUDE.md loaded up front, plus glob/grep and Bash (`head`, `tail`) for targeted just-in-time reads of large data instead of loading full objects.
- **Pre-computed retrieval**: faster; suits less dynamic corpora (legal, finance); needs opinionated engineering to avoid dead weight.
- **Hybrid**: some context up front for speed plus autonomous exploration; as models improve, the trend is toward more agent autonomy and less human curation.

### Long-horizon techniques
1. **Compaction** — near the context limit, summarize the conversation and reinitiate a fresh window with the summary. Preserve architectural decisions, unresolved bugs, implementation details; drop redundant tool outputs. Tuning method: first maximize recall, then iterate for precision. Cheap first optimization: clear old tool calls/results deep in history once consumed. Available as a context-management feature on the Claude Developer Platform.
2. **Structured note-taking / agentic memory** — the agent regularly writes notes to files outside the context window (to-do lists, `NOTES.md`) and pulls them back later; persistent memory at minimal token cost. Example: Claude playing Pokémon kept precise tallies across thousands of steps, drew maps, tracked objectives and combat strategies — developing its own tracking systems without being told to. Anthropic's file-based **memory tool** (public beta, launched with Sonnet 4.5) formalizes this: knowledge bases over time, project state across sessions.
3. **Sub-agent architectures** — specialized sub-agents do deep exploration in clean context windows (possibly tens of thousands of tokens of tool use) and return condensed summaries of 1,000–2,000 tokens to a coordinating lead agent. Clear separation of concerns; substantial gains over single-agent on complex research.

### Choosing a technique
| Technique | Best for |
|---|---|
| Compaction | Long back-and-forth where conversational flow must continue |
| Note-taking / memory files | Iterative development with clear milestones |
| Sub-agents | Parallel research/analysis where exploration pays dividends |
- No fixed token thresholds are prescribed; tune iteratively per task. Smarter models need less scaffolding and recover from errors better — expect to prune harness complexity as models improve.

## Notable quotes

> "Find the smallest set of high-signal tokens that maximize the likelihood of your desired outcome." — Anthropic

> "Every new token introduced depletes this budget by some amount, increasing the need to carefully curate tokens." — Anthropic

## Application to Ouroboros

The **Generator** should emit system prompts at the "right altitude" (sectioned, heuristic-level, failure-mode-driven) and default generated repos to just-in-time retrieval (grep/glob over identifiers) rather than pre-stuffed context. The **runner** picks the long-horizon strategy per phase: note-taking/state files for the milestone-driven build loop (Ouroboros's progress and feature files are exactly this pattern), compaction only as a fallback, and sub-agents for research/review so exploration never pollutes the implementing context — budgeting sub-agent reports at ~1–2k tokens. The **Inspector** can use context-rot awareness as a drift predictor: sessions approaching the window without a reset are higher-risk and should be flagged or force-reset.
