---
title: Demystifying Evals for AI Agents
source_url: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
publisher: Anthropic
retrieved: 2026-08-25
domain: evaluation-slop-detection
doc_type: engineering-blog
relevance: Anthropic's canonical playbook for grading agent behavior — directly shapes the Slop Inspector's grader stack and eval maintenance loop.
---

## Summary

Anthropic's engineering guide lays out how to build and maintain evaluations for AI agents. It defines the core vocabulary (task, trial, grader, transcript, outcome, harness), describes three grader families (code-based, model-based, human) with their trade-offs, and distinguishes capability evals (low pass rates, aspirational) from regression evals (near-100%, protect against backsliding). It covers non-determinism via pass@k vs pass^k, grader design principles (grade outcomes not paths, partial credit, per-dimension rubrics, human calibration), an eight-step task-development roadmap, agent-type-specific grading strategies, and common pitfalls like ambiguous tasks and grading bugs.

## Key knowledge

### Core vocabulary
- **Task**: a single test with defined inputs and success criteria. **Trial**: one attempt at a task; run multiple trials to account for model variance.
- **Grader**: logic scoring performance; one task can have multiple graders.
- **Transcript**: complete record — outputs, tool calls, reasoning, interactions. **Outcome**: final environment state (e.g., the reservation actually exists).
- **Evaluation harness**: infrastructure running evals end-to-end; distinct from the **agent harness/scaffold** that lets the model act.
- Key framing: grade the **task outcome and environment state**, then use **transcript review** to understand why the result happened.

### Three grader families
1. **Code-based**: string matching, binary tests, static analysis, outcome verification, tool-call verification, transcript analysis. Fast, cheap, objective, reproducible, easy to debug — but brittle to valid variations and lacking nuance.
2. **Model-based (LLM judge)**: rubric scoring, natural-language assertions, pairwise comparison, reference-based evaluation, multi-judge consensus. Flexible and scalable, captures nuance — but non-deterministic, expensive, and must be calibrated against human graders before trusted.
3. **Human**: SME review, crowdsourcing, spot-check sampling, A/B testing, inter-annotator agreement. Gold-standard quality but expensive and slow.

### Eval types
- **Capability/quality evals** start at low pass rates and target hard tasks; **regression evals** maintain near-100% pass rates and catch behavioral drift. Capability evals graduate into regression suites as agents improve.

### Non-determinism metrics
- **pass@k** = probability of at least one success in k attempts (rises with k). **pass^k** = probability all k trials succeed (falls with k).
- Example: 75% per-trial success → pass^3 = 0.75³ ≈ 42%.
- Use pass@k when one success matters (tooling); use pass^k for production agents needing consistency.

### Grader design principles
- Avoid over-specification: don't grade exact tool-call sequences; grade what the agent produced, not the path.
- Build partial credit for incremental progress.
- Structure LLM rubrics to grade each dimension **separately**, with clear rubrics and an explicit "Unknown" option to prevent judge hallucination.
- Calibrate model graders against expert human judgment before trusting scores.
- Design tasks so they can't be passed by exploiting loopholes (bypass prevention).

### Task development roadmap
- Step 0–1: start with 20–50 simple tasks harvested from manual testing and bug reports; don't wait for perfect datasets.
- Step 2: unambiguous tasks — "two domain experts would independently reach the same pass/fail verdict"; build reference solutions to prove solvability and validate graders.
- Step 3: balanced problem sets — test positive and negative cases; class imbalance creates one-sided optimization.
- Step 4: stable isolated environments — fresh state per trial; leftover files/cached data cause correlated failures.
- Step 5: deterministic graders where possible, LLM graders when necessary, human graders judiciously; combine grader types (Swiss Cheese layering).
- Step 6: read transcripts regularly — failures reveal whether the agent erred or the grader rejected a valid solution.
- Step 7: watch for **eval saturation** (agent passes all solvable tasks); refresh with harder tasks.
- Step 8: maintain evals like unit tests — a living artifact with dedicated infra owners and domain-expert task contributors.

### Coding-agent specifics
- Use deterministic grading (do tests pass?) combined with LLM rubrics for code quality; verify both outcome (working code) and transcript (tool usage, reasoning quality).
- SWE-bench Verified grades by running test suites; scores moved from ~40% to >80% in a year.

### Pitfalls
- Task ambiguity and rigid harness constraints unfairly fail agents — Opus 4.5 went from 42% to 95% on CORE-Bench after grading bugs were fixed and constraints loosened.
- Grading errors: fixed-decimal expectations (expecting "96.124991", penalizing "96.12"), stochastically impossible tasks.
- 0% pass@100 usually means broken tasks, not an incapable agent; never take scores at face value without reading transcripts.

### Complements to automated evals
- Production monitoring, A/B tests, user feedback, manual transcript review, and systematic human studies each catch failures the others miss.
- Frameworks: Harbor (containerized environments), Braintrust, LangSmith, Langfuse, Arize Phoenix — but eval quality matters more than framework choice.

## Notable quotes

> "Grade what the agent produced, not the path it took."

> "A good task is one where two domain experts would independently reach the same pass/fail verdict."

> "We do not take eval scores at face value until someone digs into the details of the eval and reads some transcripts."

## Application to Ouroboros

The Inspector's two-stage design mirrors this guide exactly: deterministic gates (tests, lint, scope fences) are the code-based graders; the LLM judge is the model-based layer, which per Anthropic must grade dimensions separately, offer an "Unknown" verdict, and be periodically calibrated against human review of transcripts. The runner should treat per-commit judgments as regression evals (near-100% expected) and track pass^k across an agent session rather than pass@k, since Ouroboros needs consistency across every commit, not one lucky success. The pitfall list (grader bugs, ambiguous specs) argues for the Inquisitor producing unambiguous, expert-agreement-level specs before the Generator runs.
