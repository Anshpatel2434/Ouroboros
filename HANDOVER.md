# Ouroboros — Handover

**Read this file first.** It is the complete context needed to continue work on
this project. Where it states a decision, that decision is locked and should not
be relitigated without the project owner's say-so.

---

## 1. What Ouroboros is

Ouroboros is a **meta-harness generator**. It does not build application
software — it builds the *harness* in which autonomous coding agents (Claude
Code and peers) build software safely, then polices those agents while they work.

Three subsystems:

| Subsystem | Role |
|---|---|
| **The Inquisitor** | A LangGraph interviewer that interrogates a human developer until the project spec is complete and contradiction-free. Refuses to finish while ambiguity remains. |
| **The Generator** | Turns the passed spec into an **Agent Harness Repo**: constitution, task backlog, verification suite, state files, git/CI interception wiring. |
| **The Slop Inspector** | **v2, not built.** A loop that would evaluate every commit the agent makes against the spec and propose instruction patches when it drifts. Deferred deliberately — see section 2. |

**Stack:** Python + LangGraph (orchestration), TypeScript/Next.js (local UI). A
database for the knowledge corpus — connection string not yet provided at time
of writing, so the corpus is currently retrieved from files on disk.

---

## 2. Current state of the repo

**v1 scope was narrowed on 2026-09-02 by the project owner.** The Slop Inspector
(commit-time drift detection) is deferred to v2. v1 is the **Kickoff Generator**
only: interview, ambiguity lint, generate, self-review, publish.

What that removes from v1: the hosted backend, webhooks and commit polling, PAT
monitoring, verdict feeds, and instruction-patch PRs. GitHub access returns only
at *generation* time, to create the repo and push once.

What it does not remove: the guardrails baked into the generated repo. Those are
Generator outputs, they run locally, and they cost nothing.

```
Ouroboros/
├── README.md                    <- how to run it
├── HANDOVER.md                  <- you are here
├── pyproject.toml
├── ouroboros/
│   ├── models/                  ProjectSpec, interview drafts, repo blueprints
│   ├── corpus/                  BM25 retrieval over data/collected
│   ├── inquisitor/              ambiguity lint, semantic lint, research, interview graph
│   ├── generator/               planners, templates, runner templates, review, build
│   ├── publish/                 GitHub repo creation and push
│   ├── llm/                     the structured-output layer
│   └── server/                  local FastAPI
├── web/                         local Next.js interview UI
├── tests/                       53 tests, no API key or network needed
└── data/collected/              the Knowledge Corpus (45 docs)
```

All five build slices are complete and pushed:

1. Spec contract, ambiguity lint, corpus retrieval
2. The LangGraph interview loop (questions, integration, research, lint, converge)
3. The Generator: backlog planning, skeleton planning, templates, self-review
4. The local web UI and its API
5. The runner scripts and GitHub publishing

Verified working end to end in a browser: UI to API to LLM layer, including the
error path when no API key is set. Not yet exercised against a live model — that
needs an `ANTHROPIC_API_KEY`, and is the first thing to do next.

## 3. The Knowledge Corpus

The corpus is the reason Ouroboros can promise "no guesswork". It is the
distilled body of knowledge the Generator draws on when writing a harness repo.

- **Format:** every document follows `data/collected/CURATION_GUIDE.md` —
  YAML frontmatter (`title`, `source_url`, `publisher`, `retrieved`, `domain`,
  `doc_type`, `relevance`) plus four required sections: `## Summary`,
  `## Key knowledge`, `## Notable quotes`, `## Application to Ouroboros`.
- **Content policy:** documents are *curated structured notes in our own words*,
  not mirrors of source articles. Exact facts (commands, flags, endpoints, JSON
  schemas, config keys) are copied verbatim because paraphrasing them would
  corrupt the corpus; surrounding prose is original. Do not paste full article
  text into corpus files.
- **Verification:** a compliance scan confirmed all 45 documents have complete
  frontmatter and all four sections. Re-run that check after adding documents.

### Domain coverage

- **01-harness-engineering (10)** — Anthropic's agent-engineering canon
  (building effective agents, harnesses for long-running agents, context
  engineering, writing tools for agents, multi-agent research system, Claude
  Code best practices) plus practitioner patterns: GitHub Spec Kit's
  specify → plan → tasks → implement pipeline, self-improving agent loops,
  file-based agent memory, and coding-agent security guardrails.
- **02-claude-code-mechanics (9)** — CLI reference, headless `claude -p` mode,
  Claude Agent SDK (Python/TS), hooks, CLAUDE.md memory files,
  settings/permission rule grammar, subagents + git worktrees, MCP/skills
  config, and long-session compaction/resume/cost behavior.
- **03-orchestration-langgraph (10)** — graph API, persistence/checkpointing,
  human-in-the-loop interrupts, **structured output with validation retries**
  (the mechanism behind the verdict schema), evaluator-optimizer reflection
  loops, Send-API fan-out, node retry/timeout policies, streaming, subgraphs,
  multi-agent architectures.
- **04-evaluation-slop-detection (8)** — LLM-as-judge design and bias
  mitigation, pass@k / functional correctness, mutation testing, SonarQube-style
  quality gates, GitClear's AI code-quality findings, reward-hacking taxonomy,
  and intent-drift mechanics in long sessions.
- **05-git-github-integration (8)** — fine-grained PATs, commits/compare
  endpoints, REST write operations, webhooks (push payload, HMAC validation) and
  the ETag-polling fallback, rate limits, GitHub Actions, git hooks mechanics,
  worktrees and branch protection.

---

## 4. The 18 locked decisions

These came out of the Inquisitor Phase interview. Treat them as the spec.

### Judgment model

- **D1 — Hybrid judge.** Deterministic gates run first and are non-negotiable:
  tests pass, lint clean, no TODO stubs, diff inside the task's scope fence, no
  protected-path touches. Only commits that survive the gates reach the LLM
  judge, which scores semantic alignment against `spec.md`.
- **D18 — Verdict schema.** The judge emits this object; it is the contract every
  other subsystem consumes (dashboard trends, severity-driven actions,
  notifications):

```json
{
  "spec_alignment": 0,
  "severity": "none | minor | moderate | critical",
  "verdict": "pass | slop",
  "violations": [
    {
      "rule": "<gate or rubric item violated>",
      "file": "path/to/file",
      "line": 42,
      "evidence": "<quoted diff excerpt>",
      "rectification": "<concrete fix instruction>"
    }
  ]
}
```

Every violation **must** cite evidence and a rectification — the judge is
forbidden from emitting naked opinions. Severity drives action:
none/minor → report only; moderate → quarantine candidate;
critical → quarantine + notify + patch proposal.

### Permission modes

Blast radius is defined by one user grant: GitHub write access. In **both**
modes every finding is always reported with the issue and a concrete
rectification path — reporting is unconditional, acting is permissioned.

- **D2a — Observer mode** (no write access): findings go to the Next.js
  dashboard (verdict feed, severity, alignment score, rectification steps) and
  email/webhook push for critical findings. *No repo-local report file* — the
  hosted backend and dashboard are required v1 infrastructure, not optional.
- **D2b — Enforcer mode** (write access): may open PR comments and issues,
  quarantine flagged commits to `quarantine/...` branches, and author corrective
  fix-up PRs. **Never** pushes direct reverts — the Inspector is a critic and
  co-author, not a destroyer.

### Instruction patching

- **D3 / D8 / D12.** All patches to agent instructions (`CLAUDE.md` etc.) are
  **human-approved**. The Inspector opens a real GitHub PR against the harness
  repo; **merging the PR is the approval** (fully auditable in git history).
  Approval is **non-blocking**: the agent loop keeps running on the old
  instructions until the merge lands, and the runner pulls/rebases at task
  boundaries to receive it. Patches land only inside a fenced
  `DYNAMIC DIRECTIVES` section of CLAUDE.md.
  *Accepted trade-off:* drift may compound while a patch awaits approval;
  mitigated by push notifications and the circuit breakers.

### The generated scaffold

- **D4 — Mandatory file inventory.** Every generated Agent Harness Repo contains
  all four groups. Nothing is optional.
  - **core:** `CLAUDE.md` (agent constitution with the fenced dynamic-directives
    section), `spec.md` (immutable interview-derived spec),
    `task_backlog.json` (ordered atomic tasks), `init.sh` (bootstrap + sanity check)
  - **verify:** `verify.sh` (the one command the agent runs before every commit:
    tests + lint + spec assertions) and `checks/` (per-task acceptance scripts)
  - **state:** `state/progress.json` (active task, attempt counts, last verdict)
    and `state/decisions.log` (append-only log of the agent's judgment calls)
  - **intercept:** git hooks + a GitHub Actions workflow, pre-wired
- **D5 — One-commit task granularity.** Every entry in `task_backlog.json` must
  be completable in a single commit with its own acceptance check in `checks/`.
  The Inquisitor keeps decomposing until this is true, however long that takes.
  This makes every Inspector verdict correspond to exactly one task.
- **D17 — Harness self-defense.** `CLAUDE.md`, `spec.md`, `verify.sh`, `checks/`
  and the hooks are on a **protected-path list**. Any agent diff touching them is
  an automatic **critical** verdict (quarantine + notify), enforced by the
  deterministic gate with no LLM judgment involved. The agent can never argue its
  way into editing its own guardrails.

### The Inquisitor engine

- **D6 — Refuse to generate.** The Generator will not emit a harness repo until
  every spec field passes the **ambiguity lint**: contradiction check,
  undefined-term check, missing-acceptance-criteria check. No `ASSUMPTIONS.md`
  escape hatch, no silent defaults library. The product's one promise: never a
  guessed harness.
- **D15 — Two interview surfaces from day one.** The same LangGraph interviewer
  runs behind both a CLI (`npx create-harness`-style) and the dashboard chat
  wizard. The dashboard version shows the spec building live with lint status.
- **D16 — Generation output is permission-dependent.** PAT on file → the backend
  creates the GitHub repo directly and returns a clone URL. No PAT → a
  downloadable scaffold the user pushes themselves.

### Knowledge corpus

- **D7 / D9 — Hybrid, compounding, any-stack.** A curated versioned RAG store is
  the default source at generation time, kept current by scheduled re-crawls.
  When an interview reveals a stack or tool the corpus doesn't cover, a research
  agent fills the gap live and **writes the findings back permanently** — the
  corpus compounds with every novel project. No hard stack list:
  research-then-generate. If research cannot produce confident verification
  commands for a stack, the ambiguity lint refuses generation — one gate guards
  both human ambiguity and machine ignorance.

### Runtime and loop boundaries

- **D10 — Execution topology, user-selected** at interview time; the Generator
  emits the matching runner.
  - *Driver loop:* headless Claude (Agent SDK / `claude -p`) one task at a time —
    fresh context per task, verify, commit, verdict, next. Restarts on crash,
    resumes from `state/progress.json`.
  - *Worktree fleet:* independent backlog tasks dispatched to concurrent Claude
    instances in isolated git worktrees, merged as tasks pass inspection.
- **D11 / D13 — PAT-only backend, no GitHub App in v1.** The hosted backend
  authenticates with the user's fine-grained PAT (entered via dashboard) for
  everything: detecting new commits (polling, or a webhook the user adds
  manually), pulling diffs, and all Enforcer-mode writes. One credential, one
  code path.
- **D14 — Anti-thrash: 3 strikes then park and continue.** After three failed
  inspection attempts a task is marked `BLOCKED` in `task_backlog.json` with the
  Inspector's cumulative diagnosis attached, the user is notified, and the loop
  advances to the next non-dependent task. Overnight runs survive one poisoned
  task.
- **D14 — Four mandatory circuit breakers.**
  - *budget:* user-set token/cost cap per run; pause cleanly at the cap with
    resumable state
  - *no-progress:* thrash-signature detection — repeated same-file commits with
    no verdict improvement, oscillating diffs (A → B → A), zero commits in X minutes
  - *wall-clock:* max run duration, then checkpoint and stop
  - *scope-fence:* per-task file/directory allowlist from the backlog; any
    out-of-fence diff is rejected by the deterministic gate before the LLM judge
    ever runs

---

## 5. Explicitly out of scope for v1

Rejected during the interview. Recorded so nobody relitigates them:

- Direct commit reverts by the Inspector (quarantine + fix-up PRs only)
- GitHub App registration (PAT-only; App is a v2 candidate)
- A repo-local `slop_report.md` as an Observer-mode channel (dashboard + push only)
- Autonomous or blocking instruction patches (human-merged PRs, non-blocking, only)
- Milestone- or session-grade task granularity (one-commit atoms only)
- Generating with assumptions or opinionated defaults when the spec is ambiguous
  (hard refusal only)

---

## 6. Constraints discovered during research

These came out of the corpus work and constrain the implementation:

- **GitHub check runs are GitHub-App-only.** In the PAT-only v1 the Inspector
  must report verdicts via **commit statuses, issues, and PR comments** instead.
- **Git hooks do not clone with a repository.** Generated harnesses must wire
  them through `core.hooksPath` or an install step inside `init.sh`.

---

## 7. Where to pick up

1. **Run it against a live model.** Set `ANTHROPIC_API_KEY` and take one real
   project through the whole flow. Everything is proven against a scripted LLM;
   nothing has yet met a real one. Expect the interview prompts and the backlog
   planner to need tuning after the first honest run.
2. **Revisit the generation quality gate.** v1 ships an LLM self-review as the
   only gate on generated repos, by the owner's decision. It cannot prove
   `verify.sh` runs — and the agent's first act is to run it in a loop. The seam
   for adding real scaffold execution is `generator/review.py`
   (`structural_findings` is already the non-judgement half), and our own test
   suite already executes generated scripts, so the machinery exists. Recommended
   after the first generated repo is inspected by hand.
3. **Database load.** The owner will supply a connection string. Design the
   corpus schema (documents + chunks + embeddings), load the 45 documents, and
   implement `corpus.retriever.Retriever` with a vector backend — the protocol
   exists so this swaps in without touching callers. `MANIFEST.json` was built to
   make the load mechanical.
4. **Then v2: the Slop Inspector**, on the foundation this v1 lays down.

### Working conventions

- The corpus format is enforced, not advisory — new documents must match
  `CURATION_GUIDE.md` and pass the compliance scan.
- Ouroboros should eat its own dog food: when we start building the product, the
  work should run under a harness resembling what we generate.
- Ask before assuming. The whole product exists because guesswork produces slop;
  a handover that guesses is the failure mode we are engineering against.
