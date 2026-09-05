"""Retrieval must actually surface the right corpus document for a generation query."""

from __future__ import annotations

import pytest

from ouroboros.corpus.retriever import CORPUS_ROOT, FileCorpusRetriever


@pytest.fixture(scope="module")
def retriever() -> FileCorpusRetriever:
    return FileCorpusRetriever()


def test_loader_drops_nothing(retriever):
    """The invariant that matters: every document on disk is actually loaded.

    Not a fixed count — gap research legitimately grows the corpus. Two
    documents once vanished because unquoted colons made their frontmatter
    invalid YAML, and this is the check that would have caught it.
    """
    on_disk = {
        path.stem
        for path in CORPUS_ROOT.rglob("*.md")
        if path.name not in {"README.md", "CURATION_GUIDE.md"}
    }
    loaded = {doc.slug for doc in retriever.documents}

    assert on_disk - loaded == set(), f"documents silently dropped: {on_disk - loaded}"
    assert len(retriever) == len(on_disk)


def test_curated_domains_are_all_present(retriever):
    """The seed corpus. Researched stack playbooks add domains beyond these."""
    assert {
        "harness-engineering",
        "claude-code-mechanics",
        "orchestration-langgraph",
        "evaluation-slop-detection",
        "git-github-integration",
    } <= {d.domain for d in retriever.documents}


def test_seed_corpus_is_intact(retriever):
    """The 45 curated documents must never quietly shrink."""
    curated = [d for d in retriever.documents if d.domain != "stack-playbooks"]
    assert len(curated) == 45


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
