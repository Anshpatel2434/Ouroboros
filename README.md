# Ouroboros

Interviews you until your project is unambiguous, then generates the agent
harness repo your coding agent works inside.

Not a code generator. Ouroboros produces the *harness*: the constitution, the
one-commit backlog, the verification suite, the scope fences, and the runner
that drives an autonomous agent through the work without it drifting, inventing
requirements, or quietly deleting a failing test.

## The one promise

**It refuses to generate from a spec it would have to guess about.** The
ambiguity lint blocks generation on open questions, placeholder text,
acceptance criteria no script could check, dangling dependencies, components
with no scope fence, and stacks the corpus has never researched. There is no
"generate anyway" button — that button is the entire failure mode this exists
to prevent.

## Run it

Requires Python 3.11+, Node 20+, and one model provider key.

```bash
pip install -e .
cp .env.example .env    # then put your key in it
python -m uvicorn ouroboros.server.app:app --port 8000
```

```bash
cd web && npm install && npm run dev
```

Open the printed URL (http://localhost:3000 unless that port is taken). The API
must be on port 8000, or set `NEXT_PUBLIC_API_BASE` in the web app.
`GET /api/health` reports which provider and model are actually in use.

### Model providers

| Provider | Key | Default model |
|---|---|---|
| Groq (default) | `GROQ_API_KEY` | `openai/gpt-oss-120b` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |

Groq is chosen when its key is present; `OUROBOROS_LLM_PROVIDER` overrides that,
and `OUROBOROS_DEFAULT_MODEL` / `OUROBOROS_CRITIC_MODEL` override the models.

Two things about Groq are load-bearing rather than incidental, both measured
against the live API:

- **Structured output uses `json_schema`, not tool calling.** LangChain's default
  function-calling path fails on schemas the size of `SpecDraft`. When a call is
  rejected anyway, the JSON the model produced is salvaged from the error rather
  than paid for twice.
- **The free tier allows 8,000 tokens per minute and counts requested output
  against it.** So output caps are set per role (a full spec draft needs nearly
  the whole budget; a question batch needs a fraction), prompts are trimmed to
  what is left, and a rolling token-bucket paces requests. A full interview takes
  several minutes as a result — that is the quota, not the code.
- **There is also a 200,000 token per-day ceiling**, which is roughly four to six
  complete interview-and-generate runs. That limit is detected separately and
  fails fast with a clear message, because unlike the per-minute limit, waiting
  does not fix it.

## How it works

```
brief ──▶ Inquisitor ──▶ ambiguity lint ──┬─▶ refuse, ask more
          (LangGraph)                     │
                                          └─▶ Generator ──▶ self-review ──▶ push / zip
```

1. **Interview.** Two or three questions at a time, each one naming the spec
   field it fills. Answers fold into a working draft.
2. **Research.** A stack the corpus has never seen gets researched once, and the
   findings are written back as a permanent corpus document. The corpus compounds.
3. **Lint.** Deterministic checks first (free, unarguable), then an LLM pass for
   contradictions, undefined terms, and coverage holes. Errors block generation.
4. **Generate.** Plans a one-commit backlog and a project skeleton, then renders
   the harness deterministically around them.
5. **Review.** Structural checks plus a critic model. Blocking findings send it
   back for one correction pass.
6. **Ship.** Create the repo and push with a fine-grained token, or take a zip.

## What a generated repo contains

| Path | Purpose |
|---|---|
| `CLAUDE.md` | The agent's constitution, with a fenced dynamic-directives section |
| `spec.md` | The agreed definition — immutable to the agent |
| `task_backlog.json` | One-commit tasks, each with a scope fence and completion conditions |
| `verify.sh` | The single command that decides whether work is acceptable |
| `checks/<task>.sh` | Per-task acceptance checks |
| `state/` | Progress and decision log — the agent's memory across context resets |
| `.githooks/pre-commit` | Deterministic gate: protected paths and scope fences |
| `.github/workflows/verify.yml` | The same verification, server-side |
| `runner/` | The loop: driver (serial) or fleet (parallel git worktrees) |
| *(skeleton)* | A real project whose tests already pass, so the agent starts from green |

## Repository layout

```
ouroboros/
  models/       ProjectSpec, interview drafts, repo blueprints
  corpus/       BM25 retrieval over data/collected
  inquisitor/   ambiguity lint, semantic lint, gap research, interview graph
  generator/    planners, templates, runner templates, self-review, build
  publish/      GitHub repo creation and push
  server/       the local FastAPI the UI talks to
web/            the local Next.js interview UI
data/collected/ the knowledge corpus (45 curated documents)
tests/          53 tests, no network or API key required
```

## Development

```bash
python -m pytest -q
```

Tests run against a scripted LLM (`tests/fakes.py`), so the suite needs no API
key and no network. It also executes what the generator emits — `verify.sh`, the
check scripts, and both pre-commit paths run for real in a temp directory.

## Status

v1 is the Kickoff Generator: interview, lint, generate, review, publish.
Commit-time drift detection (the Slop Inspector) is deliberately deferred — a
harness built from a precise spec prevents most drift, and detection is worth
little until generation is right. See `HANDOVER.md` for the full decision record.
