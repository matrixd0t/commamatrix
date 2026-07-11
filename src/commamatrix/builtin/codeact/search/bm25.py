# builtin/codeact/search/bm25.py

from __future__ import annotations

from collections.abc import Iterable

import bm25s

from ....api.tool import ToolDescriptor
from ..docs import ToolDocBuilder
from .api import ToolSearcher


class BM25ToolSearcher(ToolSearcher):
    def __init__(self, doc_builder: ToolDocBuilder | None = None) -> None:
        self._doc_builder = doc_builder
        self._index_fingerprint: str | None = None
        self._retriever: bm25s.BM25 | None = None
        self._ids: list[str] = []
        self._descriptors: dict[str, ToolDescriptor] = {}

    def rebuild(self, fingerprint: str, descriptors: Iterable[ToolDescriptor]) -> None:
        if fingerprint == self._index_fingerprint:
            return

        self._descriptors = {d.id: d for d in descriptors}
        self._index_fingerprint = fingerprint

        if not self._descriptors:
            self._retriever = None
            self._ids = []
            return

        self._ids = list(self._descriptors.keys())
        docs = [
            self._doc_builder.build(d) if self._doc_builder else d.doc
            for d in self._descriptors.values()
        ]

        self._retriever = bm25s.BM25()
        self._retriever.index(bm25s.tokenize(docs))

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

    def namespaces(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for d in self._descriptors.values():
            ns = d.namespace
            if ns not in seen:
                seen.add(ns)
                result.append(ns)
        return result

    def tools(self, namespace: str) -> list[ToolDescriptor]:
        prefix = namespace + '.'
        return [
            d for d in self._descriptors.values()
            if d.namespace == namespace or d.namespace.startswith(prefix)
        ]
