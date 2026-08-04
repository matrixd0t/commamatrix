# builtin/mcp/source.py

from __future__ import annotations

import hashlib
import re
import weakref
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ...components.tool import ToolDescriptor, ToolSource

if TYPE_CHECKING:
    from .manager import MCPService


def _safe_identifier(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    result = re.sub(r"_+", "_", result).strip("_") or "tool"
    if result[0].isdigit():
        result = f"_{result}"
    return result


def _suffix(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


class MCPToolSource(ToolSource):
    """Expose cached MCP tools through the regular ToolManager."""

    def __init__(self, service: MCPService) -> None:
        super().__init__()
        self.service = service

    def scan(self) -> list[ToolDescriptor]:
        descriptors: list[ToolDescriptor] = []
        aliases: dict[str, str] = {}
        names_by_alias: dict[str, set[str]] = {}
        for spec, tool in self.service.iter_tools():
            alias = self._alias(spec.server_id, aliases)
            remote_name = tool.remote_name
            name = self._name(alias, remote_name, names_by_alias)
            descriptor_id = f"mcp://{quote(spec.server_id, safe='')}/{quote(remote_name, safe='')}"
            descriptors.append(
                ToolDescriptor(
                    id=descriptor_id,
                    namespace=f"mcp.{spec.server_id}",
                    alias=alias,
                    name=name,
                    doc=tool.description,
                    schema=self._schema(tool.input_schema),
                    meta={
                        "mcp": {
                            "server_id": spec.server_id,
                            "remote_name": remote_name,
                        },
                    },
                    _source_ref=weakref.ref(self),
                )
            )
        return descriptors

    async def invoke(
        self,
        descriptor: ToolDescriptor,
        kwargs: dict[str, Any],
        ctx=None,
    ) -> object:
        metadata = descriptor.meta.get("mcp")
        if not isinstance(metadata, dict):
            raise RuntimeError(f"Tool {descriptor.id!r} has invalid MCP metadata")
        return await self.service.call_tool(
            metadata["server_id"],
            metadata["remote_name"],
            kwargs,
        )

    @staticmethod
    def _alias(server_id: str, aliases: dict[str, str]) -> str:
        base = _safe_identifier(server_id)
        alias = base
        if alias in aliases and aliases[alias] != server_id:
            alias = f"{base}_{_suffix(server_id)}"
        while alias in aliases and aliases[alias] != server_id:
            alias = f"{alias}_{_suffix(server_id)}"
        aliases[alias] = server_id
        return alias

    @staticmethod
    def _name(alias: str, remote_name: str, names_by_alias: dict[str, set[str]]) -> str:
        names = names_by_alias.setdefault(alias, set())
        base = _safe_identifier(remote_name)
        name = base
        if name in names:
            name = f"{base}_{_suffix(remote_name)}"
        while name in names:
            name = f"{name}_{_suffix(remote_name)}"
        names.add(name)
        return name

    @staticmethod
    def _schema(schema: dict[str, Any]) -> dict[str, Any]:
        result = dict(schema)
        result.setdefault("type", "object")
        result.setdefault("properties", {})
        return result


__all__ = ["MCPToolSource"]
