---
title: GitClear 2025 AI Copilot Code Quality Research (Report Summary)
source_url: https://www.jonas.rs/2025/02/09/report-summary-gitclear-ai-code-quality-research-2025.html
publisher: jonas.rs (summarizing GitClear)
retrieved: 2026-08-25
domain: evaluation-slop-detection
doc_type: reference
relevance: Quantifies what "AI slop" looks like at repo scale — duplication, churn, refactoring collapse — the empirical basis for the Inspector's slop heuristics.
---

## Summary

This is a detailed summary of GitClear's 2025 "AI Copilot Code Quality" research, which analyzed 211 million changed lines of code (2020–2024) from professional repositories to measure how AI assistants shift code-change composition. Findings: copy/pasted lines up ~48%, refactored ("moved") lines down ~60%, code churn (lines revised within two weeks) up ~84%, and an eightfold rise in duplicated code blocks in 2024. The report links these trends to declining code longevity and delivery stability, and recommends quality metrics and human review of AI-generated code. (Note: the primary GitClear report page at gitclear.com/ai_assistant_code_quality_2025_research returned HTTP 403 at retrieval time; this summary was used instead.)

## Key knowledge

### Dataset and methodology
- 211 million lines of structured code-change data spanning 2020–2024, drawn from professional developers' repositories.
- Context: 63% of developers reported using AI in 2024 (Stack Overflow survey).
- GitClear classifies every changed line into operations: added, deleted, updated, **moved** (refactoring signal), **copy/pasted**, and churned.

### Headline metrics (2020 → 2024)
| Metric | 2020 | 2024 | Change |
|---|---|---|---|
| Code addition (share of changes) | 39% | 46% | +7 pts |
| Copy/paste lines | 8.3% | 12.3% | +48% |
| Refactored ("moved") lines | 24.1% | 9.5% | −60.6% |
| Code churn (revised within 2 weeks) | 3.1% | 5.7% | +83.9% |

### Duplication
- Frequency of duplicated code blocks increased **eightfold** in 2024.
- Cited 2023 study: 57.1% of co-changed cloned code was involved in bugs — duplication is a defect vector, not just a style issue.
- 2024 was the first year copy/pasted lines exceeded moved (refactored) lines — repeated code introduction now outpaces consolidation.

### Longevity and stability
- Share of revisions touching code older than one month fell from 30% (2020) to 20% (2024) — code is reworked sooner, indicating flawed initial output.
- Google's 2024 DORA report (cited): a 7.2% decrease in delivery stability per 25% increase in AI adoption.
- High churn = developers repeatedly revising recent AI-generated code instead of doing strategic refactoring.

### Interpretation and recommendations
- AI assistance biases development toward short-term output volume over long-term maintainability ("short-term efficiency over long-term sustainability").
- Recommendations: emphasize modular design; adopt quality metrics beyond code volume (duplication density, churn rate, moved-vs-copied ratio); require experienced-developer review of AI-generated code before deployment.

### Metrics usable as slop signals
- **Copy/paste ratio** of a diff (duplicated blocks vs novel lines).
- **Churn rate**: fraction of an agent's own recent lines it rewrites within a short window.
- **Moved-vs-copied ratio**: refactoring health indicator; copy > move is a degradation signal.
- **Code longevity**: how quickly newly committed lines get revised again.

## Notable quotes

> "57.1% of co-changed cloned code was involved in bugs."

> AI prioritizes "short-term efficiency over long-term sustainability."

> DORA 2024: a "7.2% decrease in delivery stability for every 25% increase in AI adoption."

## Application to Ouroboros

These are the empirical thresholds behind the Inspector's deterministic slop gates: flag diffs with high duplicated-block density, alert when copy/paste lines outweigh moved lines across a session, and track intra-session churn (the agent rewriting its own commits from minutes ago is the two-week-churn signal compressed to agent timescale). The runner can compute GitClear-style line-operation classification per commit cheaply from the diff, feeding both a deterministic gate and evidence citations for the LLM judge ("this commit duplicates 40 lines from src/x.py"). The longevity finding justifies scoring a session, not just individual commits.
