# src/commamatrix/builtin/mcp/runtime.py

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...core.classes.service import AbstractService
from .config import MCPServerSpec
from .result import normalize_call_result

if TYPE_CHECKING:
    from ...core.agent.agent import Agent


class MCPDependencyError(RuntimeError):
    """Raised when configured MCP servers require the optional SDK."""

    def __init__(self) -> None:
        super().__init__(
            "MCP support requires the optional 'mcp' dependency. "
            "Install it with: uv sync --extra mcp"
        )


class MCPRuntimeError(RuntimeError):
    """Raised for MCP transport and session failures."""


@dataclass(frozen=True, slots=True)
class MCPToolInfo:
    remote_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


def _sdk() -> dict[str, Any]:
    try:
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client
        from mcp.types import Implementation, PaginatedRequestParams, ToolListChangedNotification
    except ModuleNotFoundError as exc:
        if exc.name == "mcp" or (exc.name and exc.name.startswith("mcp.")):
            raise MCPDependencyError from exc
        raise

    return {
        "ClientSession": ClientSession,
        "StdioServerParameters": StdioServerParameters,
        "stdio_client": stdio_client,
        "streamable_http_client": streamable_http_client,
        "sse_client": sse_client,
        "create_mcp_http_client": create_mcp_http_client,
        "Implementation": Implementation,
        "PaginatedRequestParams": PaginatedRequestParams,
        "ToolListChangedNotification": ToolListChangedNotification,
    }


class MCPServerRuntime(AbstractService):
    """Owns one long-lived MCP transport and client session."""

    def __init__(
        self,
        agent: Agent,
        spec: MCPServerSpec,
        on_tools_changed: Callable[[], None],
        client_name: str,
        client_version: str,
    ) -> None:
        super().__init__(agent)
        self.spec = spec
        self._on_tools_changed = on_tools_changed
        self._client_name = client_name
        self._client_version = client_version
        self._exit_stack: AsyncExitStack | None = None
        self._session: Any = None
        self._tools: tuple[MCPToolInfo, ...] = ()

    @property
    def tools(self) -> tuple[MCPToolInfo, ...]:
        return self._tools

    async def start(self) -> None:
        if self._session is not None:
            return

        sdk = _sdk()
        stack = AsyncExitStack()
        await stack.__aenter__()
        self._exit_stack = stack

        try:
            read_stream, write_stream = await stack.enter_async_context(self._transport(sdk))
            self._session = await stack.enter_async_context(
                sdk["ClientSession"](
                    read_stream,
                    write_stream,
                    message_handler=self._handle_message,
                    client_info=sdk["Implementation"](
                        name=self._client_name,
                        version=self._client_version,
                    ),
                )
            )
            await self._with_timeout(self._session.initialize())
            await self.refresh_tools()
        except BaseException:
            await self.stop()
            raise

    def _transport(self, sdk: dict[str, Any]):
        if self.spec.transport == "stdio":
            parameters = sdk["StdioServerParameters"](
                command=self.spec.command,
                args=list(self.spec.args),
                cwd=self.spec.cwd,
                env={**os.environ, **self.spec.env},
            )
            return sdk["stdio_client"](parameters)

        if self.spec.transport == "sse":
            return sdk["sse_client"](
                self.spec.url,
                headers=dict(self.spec.headers),
                timeout=self.spec.timeout,
                sse_read_timeout=max(self.spec.timeout, 300.0),
            )

        http_client = sdk["create_mcp_http_client"](headers=dict(self.spec.headers))
        assert self._exit_stack is not None
        self._exit_stack.push_async_callback(http_client.aclose)
        return sdk["streamable_http_client"](
            self.spec.url,
            http_client=http_client,
        )

    async def refresh_tools(self) -> tuple[MCPToolInfo, ...]:
        if self._session is None:
            raise MCPRuntimeError(f"MCP server {self.spec.server_id!r} is not connected")

        sdk = _sdk()
        cursor: str | None = None
        tools: list[MCPToolInfo] = []
        while True:
            params = (
                None
                if cursor is None
                else sdk["PaginatedRequestParams"](cursor=cursor)
            )
            result = await self._with_timeout(self._session.list_tools(params=params))
            for tool in result.tools:
                input_schema = getattr(tool, "inputSchema", None)
                if input_schema is None:
                    input_schema = getattr(tool, "input_schema", None)
                if not isinstance(input_schema, dict):
                    input_schema = {"type": "object", "properties": {}}
                tools.append(
                    MCPToolInfo(
                        remote_name=tool.name,
                        description=tool.description or f"MCP tool {tool.name}",
                        input_schema=input_schema,
                        output_schema=getattr(tool, "outputSchema", None),
                    )
                )

            cursor = getattr(result, "nextCursor", None)
            if cursor is None:
                cursor = getattr(result, "next_cursor", None)
            if not cursor:
                break

        self._tools = tuple(tools)
        return self._tools

    async def refresh(self) -> None:
        await self.refresh_tools()

    async def call_tool(self, remote_name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise MCPRuntimeError(f"MCP server {self.spec.server_id!r} is not connected")
        result = await self._with_timeout(
            self._session.call_tool(
                remote_name,
                arguments=arguments,
                read_timeout_seconds=self.spec.timeout,
            )
        )
        return normalize_call_result(result)

    async def stop(self) -> None:
        self._session = None
        self._tools = ()
        stack = self._exit_stack
        self._exit_stack = None
        if stack is not None:
            await stack.aclose()

    async def _with_timeout(self, awaitable: Awaitable[Any]) -> Any:
        async with asyncio.timeout(self.spec.timeout):
            return await awaitable

    async def _handle_message(self, message: Any) -> None:
        sdk = _sdk()
        if isinstance(message, sdk["ToolListChangedNotification"]):
            self._on_tools_changed()


__all__ = [
    "MCPDependencyError",
    "MCPRuntimeError",
    "MCPToolInfo",
    "MCPServerRuntime",
]
