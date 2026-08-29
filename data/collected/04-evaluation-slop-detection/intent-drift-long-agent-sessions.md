---
title: Intent Drift in Long Conversations — Why Your Agent's Goal Representation Goes Stale
source_url: https://tianpan.co/blog/2026-05-04-intent-drift-long-conversations-agent-goal-stale
publisher: TianPan.co
retrieved: 2026-08-25
domain: evaluation-slop-detection
doc_type: engineering-blog
relevance: Explains the mechanisms and measurable symptoms of goal drift in long agent sessions — the phenomenon the Inspector's spec-alignment score exists to catch.
---

## Summary

This engineering essay analyzes intent drift: the gap that opens between an agent's working understanding of the goal and the user's actual, evolving intent over long sessions. It identifies three root mechanisms — pattern-matching inertia (early behavior becomes self-reinforcing), token-position bias (original instructions lose effective attention weight), and training rationality (models fall back to population-level defaults). It quantifies the damage (~30% multi-turn degradation, 10–14% accuracy on explicit revisions, 2% early misalignment compounding to ~40% end-of-chain failure) and catalogs production failure patterns: scope creep, stale optimization targets, and resumption errors after context compression. The fix, it argues, is modeling intent as an explicit mutable state variable rather than an emergent property of raw context.

## Key knowledge

### Definition
- Intent drift: the agent "remembers everything but understands nothing about how the user's intent has evolved" — context is present, but its interpretation is stale.

### Three root mechanisms
1. **Pattern-matching inertia**: early behavioral patterns self-reinforce. An agent that spent 8,000 tokens on refactoring keeps behaving like a refactoring agent after the goal pivots to documentation. The model doesn't ignore the original goal — it just weights it less than the pattern of recent exchange.
2. **Token-position bias**: transformer attention is non-uniform over positions; original instructions decay in effective influence even though they remain textually in context.
3. **Training rationality**: under ambiguous signals, models revert to population-level "helpful defaults" instead of tracking this specific session's trajectory revisions.

### Quantified symptoms
- ~30% performance degradation on complex generation tasks in multi-turn vs single-turn settings.
- Models handle explicit user *revisions* correctly only 10–14% of the time — they treat a correction ("I actually meant X") as an elaboration ("I also mean X").
- An early ~2% goal misalignment compounds to roughly a 40% failure rate at the end of a long execution chain.

### Production failure patterns
- **Scope creep**: an agent told to modify specific files gradually expands into forbidden directories — the "code modification" pattern self-reinforces while the stated constraint loses enforcement.
- **Stale optimization targets**: agents silently re-optimize toward objectives inferred from offhand comments instead of explicit instructions.
- **Resumption errors**: after context compression or a pause, intent is reconstructed from summaries that dropped the latest refinements.

### The revision-vs-clarification gap
- The most insidious drift class: revisions misread as clarifications. It's structural — fixing it requires modeling intent as "a structured state variable rather than an emergent property of raw context."

### Mitigation directions (named, not detailed)
- Mutable intent representation (explicit goal state updated on every revision).
- Conversation summarization that preserves the latest intent refinements.
- Periodic intent reconciliation checkpoints.
- Architectures that re-anchor the current goal near the attention-favored end of context.

## Notable quotes

> The agent "remembers everything but understands nothing about how the user's intent has evolved."

> "The model isn't ignoring the original goal — it just weights it less than the pattern of recent exchange."

> Intent must be "a structured state variable rather than an emergent property of raw context."

## Application to Ouroboros

This is the theoretical case for per-commit inspection: drift compounds (2% → 40%), so catching a small deviation at commit N is far cheaper than diagnosing a wrecked session at commit N+30. The Inspector's scope-fence gate is the deterministic answer to scope creep — self-reinforcing modification patterns expanding into forbidden paths is exactly what a hard path allowlist stops regardless of attention decay. The Inquisitor's spec should function as the "mutable intent representation": the judge always scores the diff against the current spec document, not the conversation, immunizing evaluation from token-position bias. The runner should re-inject the spec near the end of the Generator's context each iteration, and treat post-compaction commits as elevated-risk (resumption errors), warranting stricter judging.
