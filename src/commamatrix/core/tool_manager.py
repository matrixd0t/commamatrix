# core/tool_manager.py

from __future__ import annotations

from typing import Any

from .manager import Manager
from ..api.hooks import BeforeToolCallCtx
from ..api.llm_adapter import ToolCall, ToolCallResult
from ..api.tool import ToolDescriptor, ToolSource
from ..builtin.python.tool_source import PythonToolSource


class ToolManager(Manager[ToolDescriptor]):
    """Manager for tool descriptors.

    Maintains an alias -> descriptors map for virtual imports and
    provides both raw invoke() and agent-loop-safe call() execution.
    """

    def __init__(self) -> None:
        super().__init__()
        self._python_source = PythonToolSource()
        self.mount(self._python_source)
        self._by_alias: dict[str, list[ToolDescriptor]] = {}
        self._by_name: dict[str, list[ToolDescriptor]] = {}
        self._by_exported_name: dict[str, list[ToolDescriptor]] = {}
        self._schemas: list[dict[str, Any]] = []

    def set_scope(self, scope: list[str]) -> None:
        """Point the underlying Python source at scope."""
        self._python_source.set_scope(scope)

    @property
    def fingerprint(self) -> str | None:
        return self._fingerprint

    def schemas(self) -> list[dict[str, Any]]:
        """Return JSON Schemas of all registered tools (for LLM tool definitions)."""
        return self._schemas

    def resolve(self, name: str) -> ToolDescriptor | None:
        """Resolve a tool by name.

        Resolution order:
        1. Full id (e.g. python://ns/name).
        2. exported_name (O(1) via index).
        3. alias (O(1) via index).
        4. name (O(1) via index, first match).
        """
        if name in self._descriptors:
            return self._descriptors[name]

        by_exported = self._by_exported_name.get(name)
        if by_exported:
            return by_exported[0]

        by_alias = self._by_alias.get(name)
        if by_alias:
            return by_alias[0]

        by_name = self._by_name.get(name)
        if by_name:
            return by_name[0]

        return None

    @property
    def modules(self) -> dict[str, list[ToolDescriptor]]:
        """Tools grouped by virtual module name.

        Aliases and simple namespaces become virtual Python modules for
        CodeAct. The descriptors under each module name become its callable attributes.
        """
        return self._by_alias

    def has_module(self, alias: str) -> bool:
        """Check whether a virtual module with the given alias exists."""
        return alias in self._by_alias

    def find_alias(self, alias: str) -> list[ToolDescriptor]:
        """Return all descriptors under alias."""
        return self._by_alias.get(alias, [])

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> Any:
        """Execute a tool and return the raw result (not wrapped in ToolCallResult).

        Used by CodeAct virtual-import proxy functions. Errors propagate upward.
        ctx is forwarded to the underlying ToolSource.invoke() for type-based injection.
        """
        return await self._source_of(descriptor).invoke(descriptor, kwargs, ctx=ctx)

    async def call(self, tool_call: ToolCall, ctx: BeforeToolCallCtx | None = None) -> ToolCallResult:
        """Resolve a tool by tool_call.tool_name and execute it.

        Returns a ToolCallResult with the raw Python result in content
        and graceful error handling — designed for the standard agent loop.
        """
        descriptor = self.resolve(tool_call.tool_name)
        if descriptor is None:
            return ToolCallResult(
                tool_call_id=tool_call.tool_call_id,
                content=f"Tool not found: {tool_call.tool_name!r}",
            )

        try:
            tool_source: ToolSource = self._source_of(descriptor)
            result = await tool_source.invoke(descriptor, tool_call.tool_args, ctx=ctx)
        except Exception as exc:
            return ToolCallResult(
                tool_call_id=tool_call.tool_call_id,
                content=f"Error executing tool {tool_call.tool_name!r}: {exc}",
            )

        return ToolCallResult(
            tool_call_id=tool_call.tool_call_id,
            content=result,
        )

    def _rebuild(self) -> None:
        """Rebuild the alias/name -> descriptors maps and schema cache."""
        by_alias: dict[str, list[ToolDescriptor]] = {}
        by_name: dict[str, list[ToolDescriptor]] = {}
        by_exported: dict[str, list[ToolDescriptor]] = {}
        for descriptor in self.descriptors:
            by_alias.setdefault(descriptor.alias, []).append(descriptor)
            if descriptor.namespace != descriptor.alias:
                by_alias.setdefault(descriptor.namespace, []).append(descriptor)
            by_name.setdefault(descriptor.name, []).append(descriptor)
            by_exported.setdefault(descriptor.exported_name, []).append(descriptor)
        self._by_alias = by_alias
        self._by_name = by_name
        self._by_exported_name = by_exported
        self._schemas = []
        for descriptor in self.descriptors:
            schema = dict(descriptor.schema)
            schema["name"] = descriptor.exported_name
            self._schemas.append(schema)

    @property
    def tool_tree(self) -> dict[str, Any]:
        """Nested dict of alias -> {__tools__: [descriptor dicts]} for CodeAct worker."""
        tree: dict[str, Any] = {}
        for alias, descriptors in self._by_alias.items():
            parts = alias.split(".")
            node = tree
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            leaf = parts[-1]
            node.setdefault(leaf, {})
            node[leaf].setdefault("__tools__", [])
            for d in descriptors:
                if any(existing["id"] == d.id for existing in node[leaf]["__tools__"]):
                    continue
                node[leaf]["__tools__"].append({
                    "id": d.id,
                    "name": d.name,
                    "doc": d.doc,
                    "schema": d.schema,
                    "meta": d.metadata,
                })
        return tree
