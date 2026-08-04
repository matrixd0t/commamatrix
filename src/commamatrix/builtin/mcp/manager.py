# builtin/mcp/manager.py

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ...core.classes.service import Service
from .config import (
    MCPServerSpec,
    mcp_client_name,
    mcp_client_version,
    mcp_servers,
    normalize_server_specs,
)
from .runtime import MCPServerRuntime, MCPToolInfo

if TYPE_CHECKING:
    from ...core.agent.agent import Agent
    from .source import MCPToolSource


class MCPService(Service):
    """Owns configured MCP sessions and exposes their tools to ToolManager."""

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._runtimes: dict[str, MCPServerRuntime] = {}
        self._specs: dict[str, MCPServerSpec] = {}
        self._tools: dict[str, tuple[MCPToolInfo, ...]] = {}
        self._refresh_lock = asyncio.Lock()
        self._started = False
        self._tool_source: MCPToolSource | None = None
        self._tool_source_mounted = False

    @property
    def servers(self) -> tuple[MCPServerSpec, ...]:
        return tuple(self._specs.values())

    def iter_tools(self) -> Iterable[tuple[MCPServerSpec, MCPToolInfo]]:
        for server_id, spec in self._specs.items():
            for tool in self._tools.get(server_id, ()):
                yield spec, tool

    async def call_tool(
        self,
        server_id: str,
        remote_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        runtime = self._runtimes.get(server_id)
        if runtime is None:
            raise RuntimeError(f"MCP server {server_id!r} is not configured")
        return await runtime.call_tool(remote_name, arguments)

    async def start(self) -> None:
        self._ensure_tool_source()
        async with self._refresh_lock:
            await self._reconcile(self._configured_specs(), fail_fast=True)
            self._started = True
        await self.agent.tool_manager.refresh()

    async def refresh(self) -> None:
        if not self._started:
            return
        async with self._refresh_lock:
            await self._reconcile(self._configured_specs(), fail_fast=False)
        await self.agent.tool_manager.refresh()

    async def stop(self) -> None:
        async with self._refresh_lock:
            for server_id in reversed(tuple(self._runtimes)):
                await self._runtimes[server_id].stop()
            self._runtimes.clear()
            self._specs.clear()
            self._tools.clear()
            self._started = False
        if self._tool_source is not None and self._tool_source_mounted:
            self.agent.tool_manager.unmount(self._tool_source)
            self._tool_source_mounted = False

    async def set_servers(self, servers: Any) -> None:
        """Replace server configuration and refresh active MCP tools."""
        self.config.set(mcp_servers, servers)
        if not self._started:
            return
        self._request_refresh()
        await self.agent.lifecycle.refresh(force=True)

    async def add_server(self, server: MCPServerSpec | dict[str, Any]) -> None:
        current = list(self._configured_specs())
        if isinstance(server, MCPServerSpec):
            spec = server
        else:
            server_id = server.get("server_id") or server.get("id")
            if not isinstance(server_id, str) or not server_id:
                raise ValueError("MCP server entries require server_id")
            spec = MCPServerSpec.from_value(server_id, server)
        current = [item for item in current if item.server_id != spec.server_id]
        current.append(spec)
        await self.set_servers(current)

    async def remove_server(self, server_id: str) -> None:
        remaining = [spec for spec in self._configured_specs() if spec.server_id != server_id]
        await self.set_servers(remaining)

    def _ensure_tool_source(self) -> None:
        if self._tool_source is None:
            from .source import MCPToolSource

            self._tool_source = MCPToolSource(self)
        self.agent.tool_manager.mount(self._tool_source)
        self._tool_source_mounted = True

    def _configured_specs(self) -> tuple[MCPServerSpec, ...]:
        return normalize_server_specs(self.config.get(mcp_servers))

    async def _reconcile(self, specs: tuple[MCPServerSpec, ...], *, fail_fast: bool) -> None:
        desired = {spec.server_id: spec for spec in specs if spec.enabled}

        for server_id in list(self._runtimes):
            if server_id not in desired or self._specs.get(server_id) != desired[server_id]:
                await self._runtimes[server_id].stop()
                del self._runtimes[server_id]
                self._specs.pop(server_id, None)
                self._tools.pop(server_id, None)

        client_name = self.config.get(mcp_client_name)
        client_version = self.config.get(mcp_client_version)
        for spec in desired.values():
            runtime = self._runtimes.get(spec.server_id)
            try:
                if runtime is None:
                    runtime = MCPServerRuntime(spec, self._request_refresh)
                    await runtime.start(client_name, client_version)
                    self._runtimes[spec.server_id] = runtime
                    self._specs[spec.server_id] = spec
                else:
                    await runtime.refresh_tools()
                self._tools[spec.server_id] = runtime.tools
            except Exception:
                if fail_fast:
                    raise
                if runtime is not None and spec.server_id in self._runtimes:
                    self._tools[spec.server_id] = runtime.tools

    def _request_refresh(self) -> None:
        lifecycle = getattr(self.agent, "lifecycle", None)
        if lifecycle is not None:
            lifecycle._mark_changed()


__all__ = ["MCPService"]
