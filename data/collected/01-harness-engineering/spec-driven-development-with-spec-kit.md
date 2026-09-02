---
title: "Spec-driven development with AI: Get started with a new open source toolkit"
source_url: https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/
publisher: GitHub
retrieved: 2026-08-26
domain: harness-engineering
doc_type: engineering-blog
relevance: Canonical description of the specify → plan → tasks → implement pipeline Ouroboros's Inquisitor/Generator must reproduce when turning a user's intent into an executable agent backlog.
---

## Summary

GitHub's launch post for Spec Kit describes spec-driven development (SDD): treating the specification as a living, executable artifact and the source of truth for AI coding agents, instead of throwaway "vibe-coding" prompts. The workflow has four phases — Specify, Plan, Tasks, Implement — each ending in an explicit human checkpoint where the developer verifies the generated artifact before advancing. The Specify CLI scaffolds the directory structure, templates, and agent integrations, and works with GitHub Copilot, Claude Code, and Gemini CLI. The core claim is a paradigm shift from "code is the source of truth" to "intent is the source of truth."

## Key knowledge

### The four-phase workflow

1. **Specify** — Developer supplies a high-level description of *what* is being built and *why*. The coding agent expands it into a detailed specification focused on user journeys, experiences, and success outcomes — explicitly *not* tech stack or architecture. The spec is a living artifact that evolves with user needs.
2. **Plan** — Developer supplies the desired stack, architecture, and constraints. The agent produces a technical plan that incorporates company standards, legacy-system integration, compliance requirements, and performance targets. Multiple plan variations can be generated and compared.
3. **Tasks** — The agent decomposes spec + plan into small, reviewable, independently testable chunks. Granularity example given: "create a user registration endpoint that validates email format" rather than "build authentication."
4. **Implement** — The agent executes tasks sequentially or in parallel; the developer reviews focused changes that each solve one specific problem.

### CLI and commands

- Bootstrap: `uvx --from git+https://github.com/github/spec-kit.git specify init <PROJECT_NAME>` — the Specify CLI sets up directory structures, templates, and agent integrations.
- Agent slash commands installed by the toolkit:
  - `/specify` — generate the full specification from a high-level prompt
  - `/plan` — create the technical implementation plan respecting architecture/constraints
  - `/tasks` — break specification and plan into actionable tasks
- Supported agents at launch: GitHub Copilot, Claude Code, Gemini CLI.

### Checkpoints (human-in-the-loop gates)

Every phase ends with a review gate before the next phase starts. Reviewer questions: Does the spec capture actual requirements? Does the plan account for real-world constraints? Are there edge cases or omissions? The framing: "The AI generates the artifacts; you ensure they're right."

### Rationale

- LLMs are pattern completers, not mind readers; vague prompts force the model to guess thousands of unstated requirements. A structured spec removes the guessing: the agent "knows what to build, how to build it, and in what sequence."
- Because specs capture intent, the same workflow transfers across stacks (Python, JavaScript, Go).

### Three ideal use cases

1. **Greenfield (zero-to-one)** — upfront spec/plan keeps the AI from building generic boilerplate instead of the intended product.
2. **Feature work in existing systems (N-to-N+1)** — the spec forces clarity on how the new feature interacts with an existing codebase so it integrates natively rather than being bolted on.
3. **Legacy modernization** — capture essential business logic in a modern spec, then design fresh architecture without inheriting technical debt.

### Roadmap themes GitHub named

Improved workflow engagement, VS Code integration, comparison/diffing of alternative implementations, and organization-scale spec/task management.

## Notable quotes

- "they're exceptional at pattern completion, but not at mind reading." — GitHub Blog, on why vague prompts fail
- "When your spec turns into working code automatically, it determines what gets built." — GitHub Blog

## Application to Ouroboros

- **Inquisitor**: mirrors the Specify phase — interrogate the user for intent, journeys, and success outcomes before any stack talk; keep spec (why/what) separate from plan (how). Adopt the per-phase checkpoint pattern: never advance from spec → plan → tasks without an approval gate.
- **Generator**: the generated harness repo should scaffold spec/plan/tasks artifacts the way `specify init` does — templates plus slash-command-style prompts — and emit tasks at the "one endpoint with one validation rule" granularity, each reviewable and testable in isolation.
- **Runner**: the Implement phase's "sequential or parallel over small tasks" model matches Ouroboros's loop; task independence is what makes parallelism and per-task verification possible.
- **Inspector**: checkpoint questions (requirements captured? constraints accounted for? edge cases?) are direct evaluation rubrics for judging generated specs and plans.
