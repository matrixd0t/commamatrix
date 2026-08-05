# src/commamatrix/builtin/mcp/config.py

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from ...components.config import ConfigField

MCPTransport = Literal["stdio", "streamable_http", "sse"]


@dataclass(frozen=True, slots=True)
class MCPServerSpec:
    """Connection settings for one MCP server."""

    server_id: str
    transport: MCPTransport = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout: float = 30.0

    def __post_init__(self) -> None:
        transport = self.transport.replace("-", "_")
        if transport not in {"stdio", "streamable_http", "sse"}:
            raise ValueError(f"Unsupported MCP transport: {self.transport!r}")
        if not self.server_id or not self.server_id.strip():
            raise ValueError("MCP server_id must not be empty")
        if transport == "stdio" and not self.command:
            raise ValueError("stdio MCP servers require command")
        if transport != "stdio" and not self.url:
            raise ValueError(f"{transport} MCP servers require url")
        if self.timeout <= 0:
            raise ValueError("MCP timeout must be positive")

        object.__setattr__(self, "transport", transport)
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "env", dict(self.env))
        object.__setattr__(self, "headers", dict(self.headers))

    @classmethod
    def from_value(cls, server_id: str, value: MCPServerSpec | Mapping[str, Any]) -> MCPServerSpec:
        if isinstance(value, cls):
            if value.server_id == server_id:
                return value
            return cls(
                server_id=server_id,
                transport=value.transport,
                command=value.command,
                args=value.args,
                cwd=value.cwd,
                env=value.env,
                url=value.url,
                headers=value.headers,
                timeout=value.timeout,
            )

        data = dict(value)
        data.pop("server_id", None)
        transport = data.get("transport")
        if transport is None:
            transport = "stdio" if data.get("command") else "streamable_http"
        return cls(
            server_id=server_id,
            transport=transport,
            command=data.get("command"),
            args=tuple(data.get("args", ())),
            cwd=data.get("cwd"),
            env=dict(data.get("env", {})),
            url=data.get("url"),
            headers=dict(data.get("headers", {})),
            timeout=float(data.get("timeout", 30.0)),
        )


def server_spec_to_value(spec: MCPServerSpec) -> dict[str, Any]:
    """Return a JSON-compatible representation of a server specification."""
    return {
        "server_id": spec.server_id,
        "transport": spec.transport,
        "command": spec.command,
        "args": list(spec.args),
        "cwd": spec.cwd,
        "env": dict(spec.env),
        "url": spec.url,
        "headers": dict(spec.headers),
        "timeout": spec.timeout,
    }


def normalize_server_specs(value: Any) -> tuple[MCPServerSpec, ...]:
    """Normalize list and host-style ``mcpServers`` configuration."""
    if value is None:
        return ()

    if isinstance(value, Mapping):
        if "mcpServers" in value:
            value = value["mcpServers"]
        if not isinstance(value, Mapping):
            raise TypeError("mcpServers must be a mapping of server IDs")
        specs = [MCPServerSpec.from_value(str(server_id), raw) for server_id, raw in value.items()]
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        specs = []
        for raw in value:
            if isinstance(raw, MCPServerSpec):
                specs.append(raw)
                continue
            if not isinstance(raw, Mapping):
                raise TypeError("MCP server entries must be mappings or MCPServerSpec instances")
            server_id = raw.get("server_id") or raw.get("id")
            if not isinstance(server_id, str):
                raise ValueError("MCP server entries require server_id")
            specs.append(MCPServerSpec.from_value(server_id, raw))
    else:
        raise TypeError("MCP server configuration must be a mapping or iterable")

    ids = [spec.server_id for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("MCP server IDs must be unique")
    return tuple(specs)


mcp_config_path = ConfigField[str](
    name="mcp.config_path",
    default=".commamatrix/mcp.json",
    description="Path to the built-in MCP JSON configuration file",
)

mcp_client_name = ConfigField[str](
    name="mcp.client_name",
    default="commamatrix",
    description="Client name sent during MCP initialization",
)

mcp_client_version = ConfigField[str](
    name="mcp.client_version",
    default="0.1.0",
    description="Client version sent during MCP initialization",
)


__all__ = [
    "MCPTransport",
    "MCPServerSpec",
    "server_spec_to_value",
    "normalize_server_specs",
    "mcp_config_path",
    "mcp_client_name",
    "mcp_client_version",
]
