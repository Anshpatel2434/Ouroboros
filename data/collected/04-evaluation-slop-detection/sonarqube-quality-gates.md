---
title: Understanding Quality Gates (SonarQube Server)
source_url: https://docs.sonarsource.com/sonarqube-server/2025.3/quality-standards-administration/managing-quality-gates/introduction-to-quality-gates
publisher: Sonar
retrieved: 2026-08-25
domain: evaluation-slop-detection
doc_type: official-docs
relevance: The industry-standard model for deterministic pass/fail quality gates on changed code — the pattern the Inspector's non-LLM stage implements.
---

## Summary

SonarQube quality gates are deterministic enforcement mechanisms answering "is my project ready for release?" A gate is a set of conditions — each a metric, comparison operator, and error threshold — evaluated on every analysis; failing any condition fails the gate, which can block PR merges and fail CI pipelines. The built-in read-only "Sonar way" gate embodies the Clean-as-You-Code philosophy: judge only *new* code (zero new issues, 100% of new security hotspots reviewed, ≥80% coverage on new code, ≤3% duplication on new code) rather than demanding legacy remediation. A "fudge factor" skips coverage/duplication conditions for changes under 20 lines, and a separate built-in "Sonar way for AI Code" gate targets AI-generated code.

## Key knowledge

### Model
- One quality gate per project; a default gate applies to unassigned projects. Gates "enforce a quality policy for the results of code review and analysis in your organization."
- **Condition structure**: metric + comparison operator (>, <, ≥, ≤) + error value (threshold that triggers failure). Conditions target either **new code** or **overall code**.
- Supported metric families: security/maintainability/reliability ratings, coverage, complexity, security-hotspot statistics, duplication, code size.

### Clean as You Code
- Focus enforcement on newly written/changed code instead of remediating old code — prevents new debt without demanding legacy cleanup, distributing remediation effort naturally over time.

### "Sonar way" built-in gate (default, read-only)
1. **No new issues** introduced in changed code.
2. **100% of new security hotspots reviewed**.
3. **New code coverage ≥ 80.0%**.
4. **New code duplicated lines density ≤ 3.0%**.

### Fudge factor
- Coverage and duplication conditions are **ignored when new lines < 20** (new lines to cover < 20 for coverage) — avoids overly strict enforcement on tiny changes. Enabled by default, overridable per project.

### Pass/fail semantics
- Branch analysis: both new-code and overall-code conditions apply. Pull requests: **only new-code conditions** apply, where "new code" = changes relative to the target branch.
- Failure consequences: blocks PR merges via repository-platform integration (GitHub, Bitbucket, GitLab, Azure DevOps) and fails CI pipelines. Status surfaces on project overview, PR decoration, CI reports, and subscribable email notifications.

### AI-specific gate
- A second built-in gate, **"Sonar way for AI Code"**, targets projects containing AI-generated code and marks qualifying projects with an AI Code Assurance icon — vendor acknowledgment that AI-authored code warrants distinct gating.

### Administration
- "Administer Quality Gates" permission governs creating/modifying custom gates; management via UI or Web API; project managers can associate their own projects to gates.

## Notable quotes

> "Quality gates enforce a quality policy for the results of code review and analysis in your organization."

> "This quality gate focuses on keeping high quality standards for new code, rather than spending a lot of effort remediating old code."

## Application to Ouroboros

The Inspector's deterministic stage should copy this exact shape: a gate = ordered list of (metric, operator, threshold) conditions evaluated on the **commit diff only** (Clean-as-You-Code maps perfectly to per-commit judging — never fail an agent for pre-existing debt it didn't touch). Sensible starting thresholds come straight from Sonar way: zero new lint/type errors, ≥80% coverage on changed lines, ≤3% duplicated-line density in the diff — plus a fudge-factor equivalent so a 5-line fix isn't failed on coverage. Gate verdicts are binary and cheap, so they run before the LLM judge and short-circuit it on hard failures; the runner then reports gate status the way Sonar decorates PRs — condition-by-condition, with the failing metric and threshold as machine-readable evidence.
