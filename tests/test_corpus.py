"""Retrieval must actually surface the right corpus document for a generation query."""

from __future__ import annotations

import pytest

from ouroboros.corpus.retriever import FileCorpusRetriever


@pytest.fixture(scope="module")
def retriever() -> FileCorpusRetriever:
    return FileCorpusRetriever()


def test_corpus_loads_every_document(retriever):
    assert len(retriever) == 45


def test_all_domains_present(retriever):
    assert {d.domain for d in retriever.documents} == {
        "harness-engineering",
        "claude-code-mechanics",
        "orchestration-langgraph",
        "evaluation-slop-detection",
        "git-github-integration",
    }


def test_documents_expose_key_knowledge(retriever):
    for doc in retriever.documents:
        assert doc.key_knowledge.strip(), f"{doc.slug} has no Key knowledge section"


@pytest.mark.parametrize(
    "query, expected_slug",
    [
        ("git worktrees parallel checkouts", "git-worktrees-branch-protection"),
        ("pre-commit hook core.hooksPath", "git-hooks-mechanics"),
        ("with_structured_output pydantic schema validation", "langgraph-structured-output-llm-nodes"),
        ("interrupt resume human in the loop", "langgraph-interrupts-human-in-the-loop"),
        ("headless mode print flag non-interactive", "claude-code-headless-mode"),
    ],
)
def test_retrieval_finds_the_right_document(retriever, query, expected_slug):
    hits = retriever.search(query, limit=3)
    assert expected_slug in {h.document.slug for h in hits}


def test_domain_filter_restricts_results(retriever):
    hits = retriever.search("permissions", domain="git-github-integration", limit=5)
    assert hits
    assert all(h.document.domain == "git-github-integration" for h in hits)
