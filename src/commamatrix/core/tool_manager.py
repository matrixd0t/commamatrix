# core/tool_manager.py

from __future__ import annotations

from typing import Any

from .extension_manager import ExtensionManager
from ..api.hooks import BeforeToolCallCtx
from ..api.llm_adapter import ToolCall, ToolCallResult
from ..api.tool import ToolDescriptor, ToolSource
from ..builtin.python.tool_source import PythonToolSource


class ToolManager(ExtensionManager[ToolDescriptor]):
    """
    Manager for tool descriptors.

    Maintains an alias → descriptors map for virtual imports and
    provides both raw ``invoke()`` and agent-loop-safe ``call()``
    execution.
    """

    def __init__(self) -> None:
        super().__init__()
        self.mount(PythonToolSource())
        self._by_alias: dict[str, list[ToolDescriptor]] = {}
        self._by_name: dict[str, list[ToolDescriptor]] = {}
        self._schemas: list[dict[str, Any]] = []

    @property
    def fingerprint(self) -> str | None:
        return self._fingerprint

    def schemas(self) -> list[dict[str, Any]]:
        """Return JSON Schemas of all registered tools (for LLM tool definitions)."""
        return self._schemas

    def resolve(self, name: str) -> ToolDescriptor | None:
        """
        Resolve a tool by name.

        Resolution order:
        1. Full ``id`` (e.g. ``python://ns/name``).
        2. ``alias`` (O(1) via index).
        3. ``name`` (O(1) via index, first match).
        """
        if name in self._descriptors:
            return self._descriptors[name]

        by_alias = self._by_alias.get(name)
        if by_alias:
            return by_alias[0]

        by_name = self._by_name.get(name)
        if by_name:
            return by_name[0]

        return None

    @property
    def modules(self) -> dict[str, list[ToolDescriptor]]:
        """
        Tools grouped by virtual module name.

        Aliases and simple namespaces become virtual Python modules for
        CodeAct (``from github import tool_name``). The descriptors under
        each module name become its callable attributes.
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

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> Any:
        """
        Execute a tool and return the **raw** result (not wrapped in ``ToolCallResult``).

        Used by CodeAct virtual-import proxy functions — they need the
        actual return value (e.g. a dict, a list), not a stringified version.
        Errors propagate upward for the CodeAct executor to handle.

        *ctx* is forwarded to the underlying ``ToolSource.invoke()`` for
        type-based injection into the tool function.
        """
        return await self._source_of(descriptor).invoke(descriptor, kwargs, ctx=ctx)

    async def call(self, tool_call: ToolCall, ctx: BeforeToolCallCtx | None = None) -> ToolCallResult:
        """
        Resolve a tool by ``tool_call.tool_name`` and execute it.

        Returns a ``ToolCallResult`` with the raw Python result in ``content``
        and graceful error handling — designed for the standard agent loop.

        ctx is forwarded to the underlying ``ToolSource.invoke()`` for
        type-based injection into the tool function.

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
        """Rebuild the alias/name → descriptors maps and schema cache."""
        by_alias: dict[str, list[ToolDescriptor]] = {}
        by_name: dict[str, list[ToolDescriptor]] = {}
        for descriptor in self.descriptors:
            by_alias.setdefault(descriptor.alias, []).append(descriptor)
            if descriptor.namespace != descriptor.alias:
                by_alias.setdefault(descriptor.namespace, []).append(descriptor)
            by_name.setdefault(descriptor.name, []).append(descriptor)
        self._by_alias = by_alias
        self._by_name = by_name

        self._schemas = [descriptor.schema for descriptor in self.descriptors]
