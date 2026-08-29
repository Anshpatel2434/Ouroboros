---
title: Benchmarking and Revisiting Code Generation Assessment — A Mutation-Based Approach
source_url: https://arxiv.org/pdf/2505.06880
publisher: arXiv
retrieved: 2026-08-25
domain: evaluation-slop-detection
doc_type: reference
relevance: Shows benchmark test suites are too weak to trust pass/fail alone — motivates mutation testing as a deterministic gate strengthening the Inspector's test signal.
---

## Summary

This paper challenges the reliability of test-based code-generation evaluation by applying mutation testing to benchmarks like HumanEval. Because benchmark test suites are small and weak, many "correct" (all-tests-pass) solutions actually contain latent bugs that stronger tests would expose. The authors introduce small deliberate faults (mutations) into generated solutions and measure whether the accompanying test suites kill them; low mutation scores reveal inadequate test coverage and systematic overestimation of model performance. They argue mutation scores should complement pass/fail metrics and that leaderboards built on weak suites misrepresent real solution quality.

## Key knowledge

### The core problem
- Pass/fail against a benchmark's bundled tests is only as trustworthy as the tests. HumanEval averages ~7.7 tests per problem — too few to pin down behavior.
- Consequence: a substantial portion of solutions judged correct by standard evaluation contain bugs that better-designed test cases would catch; benchmarks therefore **overstate** functional correctness.

### Mutation testing mechanics
- **Mutation**: a small, deliberate semantic change injected into code (e.g., flip an operator, off-by-one a boundary, alter a constant) producing a "mutant."
- **Mutation score** = percentage of injected mutants that the test suite detects (kills, i.e., at least one test fails on the mutant).
- Low mutation score ⇒ the tests cannot distinguish the program from many buggy variants ⇒ "all tests pass" is weak evidence of correctness.
- Applied here in two directions: (a) grading the *adequacy of benchmark test suites*, (b) exposing that passing solutions are not behaviorally equivalent to reference solutions.

### Findings
- Many HumanEval-passing solutions fail under mutation-strengthened evaluation — standard metrics miss real correctness issues.
- Mutation scores vary across models; ranking models by weak-suite pass rate can diverge from ranking by mutation-robust evaluation, so current leaderboards may misorder models.
- The gap between claimed and actual correctness argues for stricter evaluation standards field-wide.

### Recommendations
- Report mutation score alongside (or instead of) raw pass rate.
- Invest in automated test *generation/augmentation* so evaluation suites achieve high mutation adequacy before being used to certify code.
- Treat mutation testing as a quality-assurance mechanism for both the code under test and the tests themselves.

## Notable quotes

> "Test suites may not be comprehensive enough to catch all bugs in generated code."

> "Mutation testing exposes correctness issues that standard evaluation metrics miss."

## Application to Ouroboros

Directly justifies a mutation-testing gate in the Inspector's deterministic stage: when an agent's commit adds or modifies tests, run a quick mutation pass over the changed code — a low mutation score means the green test suite is vacuous (a favorite reward-hacking disguise: tests that assert nothing). It also hardens the anti-hardcoding defense from EvilGenie: mutants of a hardcoded solution survive trivially, flagging non-general code. Practical shape for the runner: mutate only diff-touched functions (budget-bounded), gate on a minimum kill-rate threshold, and pass surviving-mutant examples to the LLM judge as concrete evidence citations for a "weak tests" violation.
