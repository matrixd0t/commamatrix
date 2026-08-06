# src/commamatrix/builtin/mcp/manager.py

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.classes.service import Service
from .config import mcp_client_name, mcp_client_version, MCPServerSpec
from .loader import MCPConfigLoader, MCPJsonConfigLoader
from .runtime import MCPServerRuntime, MCPToolInfo
from .server import MCPServerManager

if TYPE_CHECKING:
    from ...core.agent.agent import Agent
    from .source import MCPToolSource


class MCPService(Service):
    """Owns configured MCP sessions and exposes their tools to ToolManager."""

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        native_json_loader = MCPJsonConfigLoader()
        native_json_loader.ensure_file(agent)
        self._loaders: list[MCPConfigLoader] = [native_json_loader]
        self._server_manager = MCPServerManager(self)
        self._refresh_lock = asyncio.Lock()
        self._config_fingerprint: str | None = None
        self._started = False
        self._tool_source: MCPToolSource | None = None
        self._tool_source_mounted = False

    @property
    def loaders(self) -> tuple[MCPConfigLoader, ...]:
        return tuple(self._loaders)

    @property
    def config_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for loader in self._loaders:
            for path in loader.paths(self.agent):
                if path not in paths:
                    paths.append(path)
        return tuple(paths)

    @property
    def client_name(self) -> str:
        return self.config.get(mcp_client_name)

    @property
    def client_version(self) -> str:
        return self.config.get(mcp_client_version)

    @property
    def servers(self) -> tuple[MCPServerSpec, ...]:
        return tuple(spec for spec, _ in self._server_manager.iter_servers())

    def iter_tools(self) -> Iterable[tuple[MCPServerSpec, MCPToolInfo]]:
        for spec, runtime in self._server_manager.iter_servers():
            for tool in runtime.tools:
                yield spec, tool

    async def call_tool(self, server_id: str, remote_name: str, arguments: dict[str, Any]) -> Any:
        runtime = self._server_manager.get_by_server_id(server_id)
        if runtime is None:
            raise RuntimeError(f"MCP server {server_id!r} is not configured")
        return await runtime.call_tool(remote_name, arguments)

    async def start(self) -> None:
        self._ensure_tool_source()
        self.logger.info("MCP service starting loaders=%d", len(self._loaders))
        async with self._refresh_lock:
            await self._server_manager.start()
            self._config_fingerprint = self._calculate_loader_fingerprint()
            self._started = True
        await self.agent.tool_manager.refresh()
        self.logger.info("MCP service started servers=%d", len(tuple(self._server_manager.iter_servers())))

    async def refresh(self) -> None:
        if not self._started:
            return
        async with self._refresh_lock:
            await self._refresh_locked()
        await self.agent.tool_manager.refresh()
        self.logger.debug("MCP service refreshed servers=%d", len(tuple(self._server_manager.iter_servers())))

    async def stop(self) -> None:
        self.logger.info("MCP service stopping")
        async with self._refresh_lock:
            await self._server_manager.stop()
            self._config_fingerprint = None
            self._started = False
        if self._tool_source is not None and self._tool_source_mounted:
            self.agent.tool_manager.unmount(self._tool_source)
            self._tool_source_mounted = False
        self.logger.info("MCP service stopped")

    async def add_loader(self, loader: MCPConfigLoader) -> None:
        """Add a configuration loader and refresh active MCP servers."""
        if not isinstance(loader, MCPConfigLoader):
            raise TypeError("MCP loaders must inherit MCPConfigLoader")
        if any(existing is loader for existing in self._loaders):
            return
        self._loaders.append(loader)
        self.logger.debug("MCP loader added loader=%s", type(loader).__name__)
        if self._started:
            await self.refresh()

    async def refresh_if_changed(self) -> bool:
        """Refresh MCP servers when any registered loader changed."""
        if not self._started:
            return False
        fingerprint = self._calculate_loader_fingerprint()
        if fingerprint == self._config_fingerprint:
            return False
        await self.refresh()
        return True

    def _load_specs(self) -> list[MCPServerSpec]:
        specs: list[MCPServerSpec] = []
        seen: set[str] = set()
        for loader in self._loaders:
            loaded = loader.load(self.agent)
            if not isinstance(loaded, list):
                raise TypeError(
                    f"{type(loader).__name__}.load() must return list[MCPServerSpec]"
                )
            for spec in loaded:
                if not isinstance(spec, MCPServerSpec):
                    raise TypeError(
                        f"{type(loader).__name__}.load() returned a non-MCPServerSpec value"
                    )
                if spec.server_id in seen:
                    raise ValueError(f"Duplicate MCP server ID: {spec.server_id!r}")
                seen.add(spec.server_id)
                specs.append(spec)
        return specs

    def _calculate_loader_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for loader in self._loaders:
            digest.update(loader.describe(self.agent).encode("utf-8"))
            digest.update(b"\0")
            digest.update(loader.fingerprint(self.agent).encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    async def _refresh_locked(self) -> None:
        await self._server_manager.refresh()
        self._config_fingerprint = self._calculate_loader_fingerprint()

    def _ensure_tool_source(self) -> None:
        if self._tool_source is None:
            from .source import MCPToolSource

            self._tool_source = MCPToolSource(self)
        self.agent.tool_manager.mount(self._tool_source)
        self._tool_source_mounted = True

    def _request_refresh(self) -> None:
        lifecycle = getattr(self.agent, "lifecycle", None)
        if lifecycle is not None:
            lifecycle._mark_changed()


__all__ = ["MCPService", "MCPConfigLoader", "MCPJsonConfigLoader", "MCPServerRuntime"]
