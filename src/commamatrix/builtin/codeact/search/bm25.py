# builtin/codeact/search/bm25.py

"""BM25-backed tool searcher using ``bm25s`` for tokenization and retrieval."""

from __future__ import annotations

from collections.abc import Iterable

import bm25s

from ....components.tool import ToolDescriptor
from .api import ToolSearcher


class BM25ToolSearcher(ToolSearcher):
    """
    Indexes ``ToolDescriptor.doc`` with BM25 for fast semantic lookup.
    All operations are synchronous by design — CodeAct does not offload them to threads.
    The BM25 index is rebuilt in-process via ``bm25s`` tokenization and scoring.
    For very large tool registries consider implementing ``ToolSearcher`` backed by an external search service instead.
    """

    def __init__(self) -> None:
        self._index_fingerprint: str | None = None
        self._retriever: bm25s.BM25 | None = None
        self._ids: list[str] = []
        self._descriptors: dict[str, ToolDescriptor] = {}

    def rebuild_index(self, fingerprint: str, descriptors: Iterable[ToolDescriptor]) -> None:
        if fingerprint == self._index_fingerprint:
            return

        new_descriptors = {d.id: d for d in descriptors}
        new_fingerprint = fingerprint

        if not new_descriptors:
            self._retriever = None
            self._ids = []
            self._descriptors = new_descriptors
            self._index_fingerprint = new_fingerprint
            return

        new_ids = list(new_descriptors.keys())
        docs = [d.doc for d in new_descriptors.values()]

        retriever = bm25s.BM25()
        retriever.index(bm25s.tokenize(docs))

        self._retriever = retriever
        self._ids = new_ids
        self._descriptors = new_descriptors
        self._index_fingerprint = new_fingerprint

    def search(self, query: str, *, limit: int = 5) -> list[ToolDescriptor]:
        if self._retriever is None or not self._ids:
            return []

        results, scores = self._retriever.retrieve(
            bm25s.tokenize(query),
            corpus=self._ids,
            k=min(limit, len(self._ids)),
        )

        return [
            self._descriptors[tool_id]
            for tool_id, score in zip(results[0], scores[0])
            if score > 0
        ]

    def aliases(self) -> list[str]:
        return list({d.alias for d in self._descriptors.values() if d.alias})

    def tools(self, alias: str) -> list[ToolDescriptor]:
        return [d for d in self._descriptors.values() if d.alias == alias] if alias else []

    @property
    def descriptors(self) -> list[ToolDescriptor]:
        return list(self._descriptors.values())
