---
title: LLM-as-a-Judge — A Complete Guide to Using LLMs for Evaluations
source_url: https://www.evidentlyai.com/llm-guide/llm-as-a-judge
publisher: Evidently AI
retrieved: 2026-08-25
domain: evaluation-slop-detection
doc_type: reference
relevance: Practical reference on judge prompt design, scoring modes, and bias mitigation — the template for the Inspector's LLM judge prompt.
---

## Summary

Evidently AI's guide covers the LLM-as-a-judge technique: using a separate LLM with a structured evaluation prompt to grade AI-generated outputs against custom criteria. It contrasts pairwise comparison, reference-free direct scoring, and reference-based evaluation; walks through a five-step workflow for building and validating a judge (define scenario, build dataset, label manually, craft prompt, iterate against human labels); and catalogs prompt-design best practices — binary over fine-grained scales, explicit label definitions, criteria separation, chain-of-thought, structured JSON output, low temperature. It names the three classic judge biases (position, verbosity, self-enhancement) with mitigations.

## Key knowledge

### Why it works
- Assessment is an easier task than generation: "classifying content is simpler than generating it," so a judge model can reliably grade outputs its peer produced.

### Three evaluation modes
1. **Pairwise comparison**: judge picks the better of two candidate responses. GPT-4 achieved over 80% agreement with human preferences — comparable to human-human agreement. Best for development-phase model/prompt selection, not production.
2. **Direct scoring (reference-free)**: judge scores a single response on defined dimensions (tone, clarity, conciseness, politeness). Works offline and in production monitoring. Can be binary classification or a graded scale.
3. **Reference-based**: judge compares against extra context — answer vs reference answer (correctness), answer vs question (completeness/relevance), answer vs retrieved context (hallucination detection for RAG), context-relevance labeling for ranking metrics.

### Judge-building workflow
1. Define the scenario/property to evaluate.
2. Build an evaluation dataset with diverse, challenging examples.
3. Manually label it to create ground truth reflecting your expectations.
4. Write the evaluation prompt with explicit scoring definitions.
5. Evaluate the judge against manual labels using precision/recall; iterate until acceptable.

### Prompt design best practices
- **Prefer binary / low-precision scoring**: binary evaluations are more reliable and consistent for both LLMs and humans; LLMs generate text, not calibrated probability scores, so avoid 0–100 fine-grained scales without anchors.
- **Define every label explicitly** — don't just ask for "toxic / not toxic"; spell out what qualifies.
- **Separate criteria**: split complex evaluations into multiple focused judges rather than one omnibus rubric; keeps cognitive load low.
- **Few-shot examples**: include input→judgment pairs, but test for biases introduced by example choice and ordering.
- **Chain-of-thought**: require step-by-step reasoning before the verdict; significantly improves judgment quality and leaves a debugging trail.
- **Structured output**: emit JSON for mechanical parsing.
- **Low temperature** for consistency.
- **Model choice**: start with the most capable model, then try downsizing once calibrated.

### Biases and mitigations
- **Position bias**: favors first or last response in a pair → randomize order, or use direct scoring instead of comparative ranking.
- **Verbosity bias**: prefers longer answers regardless of accuracy → instruct explicitly that length is not quality.
- **Self-enhancement bias**: favors text produced by the same model family → hide provenance; consider a different judge model than the generator.

### Operational notes
- Advantages: near-human quality when configured well, no reference answers needed in production, criteria are editable prompts, scales to thousands of evaluations, usable by non-technical domain experts.
- Limitations: imperfect and prompt-sensitive, inherits training biases, privacy exposure via third-party APIs, slower/costlier than rule-based checks, identical inputs can get different verdicts without repeated polling.
- Production loop: trace user interactions, run scheduled judge evaluations on samples, dashboard the metrics over time, alert on degradation, and keep a manual-review channel for continuous validation of the judge itself.

## Notable quotes

> "Classifying content is simpler than generating it."

> "Binary evaluations... tend to be more reliable and consistent for both LLMs and human evaluators."

> "Don't just ask the LLM to label something as 'toxic' or 'not toxic'. Instead, clearly define what 'toxic' means."

## Application to Ouroboros

This is the direct template for the Inspector's judge prompt: reference-based evaluation (commit diff vs spec = answer vs reference), chain-of-thought reasoning before verdict, JSON-structured output, low temperature, and a separate focused judge per criterion rather than one omnibus score. The 0–100 spec-alignment score should be anchored by explicit band definitions (or decomposed into binary sub-checks aggregated to a score), since raw fine-grained scales are unreliable. Bias mitigations matter because the Generator and Inspector may share a model family — self-enhancement bias argues for a distinct judge model or provenance hiding. The judge itself needs an eval set: manually-labeled good/slop commits with precision/recall tracking.
