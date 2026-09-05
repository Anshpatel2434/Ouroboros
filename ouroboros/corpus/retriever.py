"""Retrieval over the curated knowledge corpus in `data/collected`.

The corpus is what stops generation from being generic: at generation time we
pull the real mechanics for the user's stack — actual test commands, hook wiring,
SDK options — instead of emitting a template full of placeholders.

This is the file-backed implementation. When the database arrives, a
vector-backed retriever implements the same `Retriever` protocol and swaps in
without touching callers.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

CORPUS_ROOT = Path(__file__).resolve().parents[2] / "data" / "collected"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WORD = re.compile(r"[a-z0-9][a-z0-9._-]*")

# Words too common in this corpus to carry signal.
_STOPWORDS = frozenset(
    """the a an and or of to in for on with is are be as by that this it from at
    how what when which not but if then than so we our you your they their can
    use used using each every all any more most other some such only own same
    also into out up down over under again further once here there where why
    both few own too very just should now agent agents claude code docs doc""".split()
)


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1]


@dataclass
class CorpusDocument:
    """One curated corpus document, parsed from disk."""

    path: Path
    domain: str
    title: str
    source_url: str
    publisher: str
    doc_type: str
    relevance: str
    body: str
    _terms: Counter[str] = field(default_factory=Counter, repr=False)

    @property
    def slug(self) -> str:
        return self.path.stem

    def section(self, heading: str) -> str | None:
        """Return one `## heading` section's text, if present."""
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(self.body)
        return match.group(1).strip() if match else None

    @property
    def key_knowledge(self) -> str:
        """The section generation actually consumes."""
        return self.section("Key knowledge") or self.body


@dataclass
class RetrievalHit:
    document: CorpusDocument
    score: float


class Retriever(Protocol):
    """Swappable retrieval backend (file-backed now, vector-backed later)."""

    def search(
        self, query: str, *, domain: str | None = None, limit: int = 5
    ) -> list[RetrievalHit]: ...


def _parse_document(path: Path) -> CorpusDocument | None:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        return None

    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end():]
    doc = CorpusDocument(
        path=path,
        domain=str(meta.get("domain", path.parent.name)),
        title=str(meta.get("title", path.stem)),
        source_url=str(meta.get("source_url", "")),
        publisher=str(meta.get("publisher", "")),
        doc_type=str(meta.get("doc_type", "")),
        relevance=str(meta.get("relevance", "")),
        body=body,
    )
    # Title and relevance describe what the document is *for*, so they get
    # weighted more heavily than the body when matching a query.
    doc._terms = Counter(_tokenize(body))
    doc._terms.update({t: 3 for t in _tokenize(f"{doc.title} {doc.relevance}")})
    return doc


class FileCorpusRetriever:
    """BM25-style lexical retrieval over the on-disk corpus."""

    K1 = 1.4
    B = 0.75

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or CORPUS_ROOT
        self.documents: list[CorpusDocument] = []
        self._doc_freq: Counter[str] = Counter()
        self._avg_len = 0.0
        self._load()

    def _load(self) -> None:
        skip = {"README.md", "CURATION_GUIDE.md"}
        for path in sorted(self.root.rglob("*.md")):
            if path.name in skip:
                continue
            doc = _parse_document(path)
            if doc:
                self.documents.append(doc)

        if not self.documents:
            return
        for doc in self.documents:
            self._doc_freq.update(set(doc._terms))
        self._avg_len = sum(sum(d._terms.values()) for d in self.documents) / len(
            self.documents
        )

    def _idf(self, term: str) -> float:
        n = len(self.documents)
        df = self._doc_freq.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(
        self, query: str, *, domain: str | None = None, limit: int = 5
    ) -> list[RetrievalHit]:
        terms = _tokenize(query)
        candidates = [
            d for d in self.documents if domain is None or d.domain == domain
        ]

        hits: list[RetrievalHit] = []
        for doc in candidates:
            length = sum(doc._terms.values()) or 1
            score = 0.0
            for term in terms:
                tf = doc._terms.get(term, 0)
                if not tf:
                    continue
                norm = tf * (self.K1 + 1) / (
                    tf + self.K1 * (1 - self.B + self.B * length / (self._avg_len or 1))
                )
                score += self._idf(term) * norm
            if score > 0:
                hits.append(RetrievalHit(document=doc, score=round(score, 3)))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def register(self, path: Path) -> CorpusDocument | None:
        """Add a document written after this retriever was built.

        Gap research writes a playbook mid-interview; without this the retriever
        keeps its startup snapshot, the next lookup misses, and the same stack
        gets researched again on every round.
        """
        document = _parse_document(Path(path))
        if document is None:
            return None

        self.documents = [d for d in self.documents if d.slug != document.slug]
        self.documents.append(document)
        self._doc_freq.update(set(document._terms))
        self._avg_len = sum(sum(d._terms.values()) for d in self.documents) / len(
            self.documents
        )
        return document

    def by_domain(self, domain: str) -> list[CorpusDocument]:
        return [d for d in self.documents if d.domain == domain]

    def get(self, slug: str) -> CorpusDocument | None:
        return next((d for d in self.documents if d.slug == slug), None)

    def __len__(self) -> int:
        return len(self.documents)
