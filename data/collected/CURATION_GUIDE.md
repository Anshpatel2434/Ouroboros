# Ouroboros Knowledge Corpus — Curation Guide

Every document in `data/collected/` follows this format so the corpus can be
chunked, embedded, and loaded into the database mechanically.

## File placement

```
data/collected/
  01-harness-engineering/       # agent harness & loop engineering patterns
  02-claude-code-mechanics/     # Claude Code CLI, Agent SDK, hooks, CLAUDE.md, headless ops
  03-orchestration-langgraph/   # LangGraph + multi-agent orchestration patterns
  04-evaluation-slop-detection/ # LLM-as-judge, code eval, drift/slop detection
  05-git-github-integration/    # PATs, webhooks, REST API, git hooks, Actions
  MANIFEST.json                 # machine-readable index of every document
  README.md                     # human-readable index
```

## Document format

One source per file, kebab-case filename. Required frontmatter:

```markdown
---
title: <document title>
source_url: <canonical URL>
publisher: <e.g. Anthropic, LangChain, GitHub>
retrieved: YYYY-MM-DD
domain: <directory name without number prefix>
doc_type: official-docs | engineering-blog | reference
relevance: <one line — why Ouroboros needs this>
---
```

Required sections, in order:

1. `## Summary` — 3–6 sentences.
2. `## Key knowledge` — comprehensive structured notes **in our own words**:
   every technical fact, command, flag, schema, API shape, pattern, threshold,
   and gotcha the source contains. This is the section the RAG store will
   mostly retrieve from — completeness of *facts* matters more than prose.
3. `## Notable quotes` — at most 3 short attributed quotes (<25 words each).
4. `## Application to Ouroboros` — which subsystem consumes this (Inquisitor,
   Generator, Inspector, runner) and how.

## Rules

- Notes, not mirrors: capture the knowledge in our own words; do not paste
  full article text into the corpus.
- Facts (commands, JSON schemas, API endpoints, config keys) are copied
  exactly — paraphrasing a flag name corrupts the corpus.
- Every file must be self-contained: a reader with no other context should
  understand what the source teaches.
- If a source is unreachable, do not fabricate its content; note it in the
  manifest as `status: unreachable` with the URL.
- Frontmatter must be valid YAML. Any value containing a colon-space, a leading
  `#`, or a leading `[`/`{` has to be double-quoted — titles like
  `"Spec-driven development with AI: Get started"` parse as a nested mapping
  otherwise, and the retriever silently drops the document.
- `tests/test_corpus.py` is the enforcement: it loads every document and asserts
  the expected count, so a malformed file fails the suite rather than vanishing.
