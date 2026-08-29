---
title: Writing effective tools for agents
source_url: https://www.anthropic.com/engineering/writing-tools-for-agents
publisher: Anthropic
retrieved: 2026-08-25
domain: harness-engineering
doc_type: engineering-blog
relevance: Evaluation-driven methodology for designing the tool surface of an agent harness — consolidation, namespacing, response formats, token budgets — governing every tool Ouroboros bakes into generated repos.
---

## Summary

This Anthropic post treats tools as a contract between deterministic systems and non-deterministic agents, and lays out an end-to-end workflow: prototype tools quickly (local MCP server, `claude mcp add`), evaluate them against dozens of realistic multi-step tasks with ground truth, analyze transcripts and metrics, then let Claude itself refactor the tools from the transcripts. Design guidance centers on fewer consolidated tools over many granular ones, namespaced names, high-signal natural-language responses over cryptic identifiers, aggressive token-efficiency measures (pagination, truncation, actionable errors), and meticulously prompt-engineered descriptions — which alone produced state-of-the-art SWE-bench results.

## Key knowledge

### Principles
- Tools are "a new kind of software": a contract between deterministic systems and non-deterministic agents. Ergonomic for agents ≈ intuitive for humans.
- More tools is not better; each tool should expand the set of successful strategies, not the decision surface.

### Prototyping workflow
- Stand up a quick prototype; give Claude LLM-friendly docs (check official docs for `llms.txt`).
- Wrap tools in a local MCP server or Desktop extension; connect to Claude Code with `claude mcp add <name> <command> [args...]`.
- Test manually to find rough edges before formal evals.

### Evaluation workflow
- Generate dozens of realistic prompt–response task pairs grounded in real use, each with a verifiable outcome/ground truth. Avoid toy sandboxes.
- Strong tasks require many (possibly dozens of) chained tool calls, e.g. "Customer ID 9182 was charged three times — find the logs and check whether other customers were affected." Weak tasks are single-call lookups.
- Run evals as a simple agentic while-loop over direct LLM API calls, one loop per task; have the agent output reasoning before tool calls (chain-of-thought) and enable interleaved thinking to probe tool-use decisions.
- Metrics to collect: top-level accuracy; per-tool-call runtime; total task time; number of tool calls; total token consumption; tool error frequency/types.
- Analysis: read the agent's reasoning and full transcripts; look for confusion, contradictory descriptions, redundant calls (signals pagination/token-limit tuning). Real example: Claude's web search biased results by appending "2025" to queries — fixed via the tool description.
- Use held-out test sets to avoid overfitting tool designs to the training evals.
- Meta-loop: concatenate eval transcripts, paste into Claude Code, and let Claude refactor many tools at once — it maintains cross-tool consistency and beat expert-written implementations on held-out sets (internal Slack and Asana MCP servers).

### Choosing/consolidating tools
- Fewer, thoughtful tools targeting high-impact workflows; consolidate chained operations into one tool:
  - `list_users` + `list_events` + `create_event` → one `schedule_event` with built-in availability search.
  - `read_logs` → `search_logs` returning only relevant lines with surrounding context.
  - `get_customer_by_id` + `list_transactions` + `list_notes` → `get_customer_context`.
- Rationale: agent context is expensive cognitive currency while computer memory is cheap — don't make the agent page raw data through its context (use `search_contacts`, not `list_contacts`).
- Match tools to how a human would naturally subdivide the task; overlapping tools distract agents from efficient strategies.

### Namespacing
- Group related tools under common prefixes to delineate boundaries: service-based (`asana_search`, `jira_search`) or resource-based (`asana_projects_search`, `asana_users_search`).
- Prefix vs suffix choice has non-trivial, model-dependent effects on tool-use evals — test both.
- Good namespacing offloads decision work from the agent's context into the tool structure, reducing error rates.

### Returning meaningful context
- Return high-signal semantic fields (`name`, `image_url`, `file_type`), not low-level identifiers (`uuid`, `256px_image_url`, `mime_type`). Resolving opaque UUIDs to natural language (or 0-indexed IDs) measurably improves precision and cuts hallucinations.
- Offer a `response_format` enum parameter (`DETAILED` / `CONCISE`) so downstream calls can request technical IDs only when needed. Slack-tool example: detailed = 206 tokens (includes `thread_ts`, `channel_id`, `user_id` for chained calls), concise = 72 tokens (~1/3 the tokens).
- Response structure (JSON vs XML vs Markdown) genuinely affects performance and is task/model dependent — evaluate, don't assume.

### Token efficiency
- Implement pagination, range selection, filtering, and truncation with sensible defaults. Reference point: Claude Code caps tool responses at 25,000 tokens by default.
- Truncation messages should steer the agent toward targeted strategies (many small searches over one broad dump).
- Error engineering: replace stack traces/opaque codes with actionable guidance, e.g. "Try filtering by date range using format YYYY-MM-DD or limit results using limit=50", plus examples of valid input.

### Tool descriptions
- Write descriptions as if onboarding a new team member: make implicit context explicit (query formats, niche terminology, resource relationships); use unambiguous parameter names (`user_id`, not `user`).
- Small description refinements produce outsized gains: precise tool-description tuning took Claude Sonnet 3.5 to state-of-the-art on SWE-bench Verified.
- MCP tool annotations should disclose open-world access and destructive operations.

### Workflow loop
1. Prototype → 2. Evaluate on realistic tasks → 3. Analyze transcripts/metrics → 4. Let Claude optimize → 5. Repeat with held-out sets.

## Notable quotes

> "Tools are a new kind of software which reflects a contract between deterministic systems and non-deterministic agents." — Anthropic

> "Small refinements to tool descriptions can yield dramatic improvements." — Anthropic

## Application to Ouroboros

The **Generator** applies the design rules to every tool surface it emits into a repo: consolidated workflow-shaped tools, namespaced names, `response_format`-style verbosity control, 25k-token response caps, and actionable error strings. The **Inspector** adopts the evaluation methodology wholesale — realistic multi-call tasks with ground truth, transcript reading, and the six metric types — as its harness-regression suite, with held-out tasks to prevent overfitting generated harnesses to their own evals. The transcript-driven "let Claude refactor the tools" meta-loop is a candidate self-improvement stage for the **runner** between projects.
