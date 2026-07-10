# core/tool_runtime.py

from __future__ import annotations

import json
from typing import Any

import bm25s

from .extension_runtime import ExtensionRuntime
from ..api.llm_adapter import ToolCall, ToolCallResult
from ..api.tool import DEFAULT_TOOL_SEARCH_AMOUNT, ToolDescriptor


class ToolRuntime(ExtensionRuntime[ToolDescriptor]):
    """
    Runtime for tool descriptors.

    Maintains a BM25 search index over tool docs, an alias → descriptors
    map for virtual imports, and provides both raw ``invoke()`` and
    agent-loop-safe ``call()`` execution.
    """

    def __init__(self) -> None:
        super().__init__()
        self._retriever: bm25s.BM25 | None = None
        self._ids: list[str] = []
        self._by_alias: dict[str, list[ToolDescriptor]] = {}

    def schemas(self) -> list[dict[str, Any]]:
        """Return JSON Schemas of all registered tools (for LLM tool definitions)."""
        return [tool.schema for tool in self.descriptors]

    def resolve(self, name: str) -> ToolDescriptor | None:
        """
        Resolve a tool by name.

        Resolution order:
        1. Full ``id`` (e.g. ``python://ns/name``).
        2. ``alias``.
        3. ``name`` (first match).
        """
        if name in self._descriptors:
            return self._descriptors[name]

        for descriptor in self._descriptors.values():
            if descriptor.alias == name:
                return descriptor

        for descriptor in self._descriptors.values():
            if descriptor.name == name:
                return descriptor

        return None

    @property
    def modules(self) -> dict[str, list[ToolDescriptor]]:
        """
        Tools grouped by alias.

        Each alias becomes a virtual Python module for CodeAct
        (``import github`` → finds ``github`` alias).  The descriptors
        under that alias become the module's callable attributes.
        """
        return self._by_alias

    def has_module(self, alias: str) -> bool:
        """Check whether a virtual module with the given alias exists."""
        return alias in self._by_alias

    def find_alias(self, alias: str) -> list[ToolDescriptor]:
        """
        Return all descriptors under *alias*.

        Returns an empty list if the alias is unknown.
        """
        return self._by_alias.get(alias, [])

    def search(
        self,
        query: str,
        *,
        limit: int = DEFAULT_TOOL_SEARCH_AMOUNT,
    ) -> list[ToolDescriptor]:
        """
        Semantic search over tool docs using BM25.

        Returns up to *limit* descriptors whose docs best match *query*,
        sorted by relevance descending.
        """
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

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any]) -> Any:
        """
        Execute a tool and return the **raw** result (not wrapped in ToolCallResult).

        Used by CodeAct virtual-import proxy functions — they need the
        actual return value (e.g. a dict, a list), not a stringified version.
        Errors propagate upward for the CodeAct executor to handle.
        """
        return await descriptor.source.invoke(descriptor, kwargs)

    async def call(self, tool_call: ToolCall) -> ToolCallResult:
        """
        Resolve a tool by ``tool_call.tool_name`` and execute it.

        Returns a ``ToolCallResult`` with stringified content and graceful
        error handling — designed for the standard (non-CodeAct) agent loop.

        Errors during execution are caught and returned as a ``ToolCallResult``
        with an error message, rather than raising.
        """
        descriptor = self.resolve(tool_call.tool_name)
        if descriptor is None:
            return ToolCallResult(
                tool_call_id=tool_call.tool_call_id,
                content=f"Tool not found: {tool_call.tool_name!r}",
            )

        try:
            result = await descriptor.source.invoke(descriptor, tool_call.tool_args)
        except Exception as exc:
            return ToolCallResult(
                tool_call_id=tool_call.tool_call_id,
                content=f"Error executing tool {tool_call.tool_name!r}: {exc}",
            )

        if isinstance(result, str):
            content = result
        else:
            content = json.dumps(result, ensure_ascii=False, default=str)

        return ToolCallResult(
            tool_call_id=tool_call.tool_call_id,
            content=content,
        )

    def _rebuild(self) -> None:
        """Rebuild the BM25 search index and the alias → descriptors map."""
        self._retriever = bm25s.BM25()

        docs = [tool.doc for tool in self.descriptors]
        self._ids = [tool.id for tool in self.descriptors]

        by_alias: dict[str, list[ToolDescriptor]] = {}
        for descriptor in self.descriptors:
            by_alias.setdefault(descriptor.alias, []).append(descriptor)
        self._by_alias = by_alias

        if not docs:
            return

        self._retriever.index(bm25s.tokenize(docs))
