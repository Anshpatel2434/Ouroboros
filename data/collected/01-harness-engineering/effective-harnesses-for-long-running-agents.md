---
title: Effective harnesses for long-running agents
source_url: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
publisher: Anthropic
retrieved: 2026-08-25
domain: harness-engineering
doc_type: engineering-blog
relevance: The canonical blueprint for the exact artifact Ouroboros generates — a multi-session harness (initializer + coder agents, feature list, progress files) that keeps a coding agent on-spec across context resets.
---

## Summary

Anthropic's engineering post (Justin Young, Nov 2025) addresses the core problem of long-running coding agents: complex projects span many context windows, and each new session starts with no memory of the previous one. Even frontier models (Claude Opus 4.5) fail to build production-quality apps from a high-level prompt alone, and built-in compaction is not sufficient for multi-window work. The solution is a two-agent harness: an *initializer agent* that runs once to set up the environment (feature list, git repo, init script, progress file), and a *coding agent* that is repeatedly woken up, makes incremental single-feature progress, verifies end-to-end, and leaves the repo in a clean, mergeable state with a written handoff. The post maps each observed failure mode to a specific harness mechanism.

## Key knowledge

### Problem framing
- Agents work in discrete sessions; there is no memory between context windows — every session boots cold.
- Compaction (summarize-and-continue, built into the Claude Agent SDK) is insufficient alone: summaries do not always carry clear enough instructions into the next session. For very long jobs, the harness must do full context resets and rebuild the session from structured artifacts on disk.
- Naive behavior without a harness: the agent tries to "one-shot" the whole app, runs out of context mid-implementation, and the next session inherits half-finished, undocumented features.

### Two-agent architecture
- **Initializer agent** — runs only in the first session, with a specialized environment-setup prompt. It:
  - Expands the user's high-level prompt into a structured `feature_list.json` of comprehensive end-to-end features.
  - Initializes a git repository and makes an initial commit.
  - Writes `init.sh` — a script future sessions run to start the development server.
  - Creates `claude-progress.txt` — a human-readable log of work across sessions.
- **Coding agent** — every subsequent session; same system prompt, tools, and harness. Mandate: make incremental progress on ONE feature, then leave the environment in a clean state.

### Key artifacts
- `init.sh` — environment/dev-server startup script; read and run at the start of every session so no session wastes context re-deriving setup.
- `claude-progress.txt` — cross-session progress notes; paired with git history it lets a fresh session reconstruct prior work without guessing.
- `feature_list.json` — structured feature tracking. Entry shape:
  ```json
  {
    "category": "functional",
    "description": "Feature description",
    "steps": ["step1", "step2"],
    "passes": false
  }
  ```
  - All features start `"passes": false`; agents may ONLY flip the `passes` field, never remove or edit features.
  - 200+ features recommended for a complex app.
  - JSON chosen over Markdown deliberately: the model is less likely to inappropriately rewrite a JSON file than a Markdown one.
  - Hard instruction in the prompt: "It is unacceptable to remove or edit tests."

### Failure mode → harness mechanism mapping
| Failure mode | Initializer fix | Coding-agent fix |
|---|---|---|
| Declares victory prematurely | Create structured feature list | Read list; work one feature at a time |
| Leaves buggy/undocumented code | Init git repo + progress file | Read progress + git log; smoke-test at start; commit + update notes at end |
| Marks features done without testing | Set up feature list with `passes` flags | Verify each feature end-to-end before flipping `passes` |
| Wastes context re-configuring environment | Write `init.sh` | Run `init.sh` at session start |

### Session startup protocol (coding agent, in order)
1. Run `pwd` to confirm working directory.
2. Read git logs and `claude-progress.txt`.
3. Read `feature_list.json`; pick the highest-priority incomplete feature.
4. Run `init.sh` to start the dev server.
5. Run a basic end-to-end smoke test (e.g., new chat → send message → get response) to detect a broken inherited state; fix existing bugs before starting new work.
6. Implement the chosen feature.

### Verification practices
- Observed gotcha: Claude marks features complete after only unit tests or `curl` checks; these are insufficient proxies for user-visible correctness.
- Fix: browser automation (Puppeteer MCP server) so the agent tests features the way an end user would, with screenshots for visual verification. This dramatically improved results.
- Known limitation: the browser tooling cannot see native `alert()` modals, so features depending on them stayed buggier.

### Clean-state contract (end of every session)
- Code is mergeable-to-main quality: no major bugs, orderly, documented.
- A descriptive git commit after each change (git enables reverting bad code and recovering working states).
- `claude-progress.txt` updated with a summary of what was done.

### Future directions flagged by the post
- Single general-purpose agent vs. specialized multi-agent (testing agent, QA agent, cleanup agent) is an open question.
- Pattern is expected to generalize beyond full-stack web dev to scientific research and financial modeling.

## Notable quotes

> "Each new session begins with no memory of what came before." — Justin Young, Anthropic

> "It is unacceptable to remove or edit tests." — harness prompt instruction, Anthropic

## Application to Ouroboros

This is the direct template for the **Generator**: every generated repo should ship an initializer phase (spec → `feature_list.json`, git init, `init.sh`, progress file) and a per-session coding prompt enforcing the one-feature/clean-state/commit contract. The **runner** implements the session startup protocol (pwd → progress → feature pick → init.sh → smoke test) and the full-context-reset loop instead of relying on compaction. The **Inspector** enforces the guardrails mechanically: features may only flip `passes`, tests may not be edited or deleted, every session must end with a commit and an updated progress file, and `passes: true` requires end-to-end (browser-level) evidence. The **Inquisitor** should elicit enough detail to produce the 200+ item feature list up front.
