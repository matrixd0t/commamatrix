# src/commamatrix/builtin/mcp/__init__.py

from . import hooks, instructions
from .config import (
    MCPServerSpec,
    MCPTransport,
    mcp_client_name,
    mcp_client_version,
    mcp_config_path,
    normalize_server_specs,
    server_spec_to_value,
)
from .loader import MCPConfigLoader, MCPJsonConfigLoader
from .manager import MCPService
from .result import MCPToolError, normalize_call_result
from .runtime import MCPDependencyError, MCPRuntimeError, MCPServerRuntime, MCPToolInfo
from .server import MCPServerDescriptor, MCPServerManager, MCPServerSource
from .source import MCPToolSource

__all__ = [
    "MCPConfigLoader",
    "MCPDependencyError",
    "MCPJsonConfigLoader",
    "MCPRuntimeError",
    "MCPServerDescriptor",
    "MCPServerManager",
    "MCPServerRuntime",
    "MCPServerSource",
    "MCPServerSpec",
    "MCPService",
    "MCPToolError",
    "MCPToolInfo",
    "MCPToolSource",
    "MCPTransport",
    "hooks",
    "instructions",
    "mcp_client_name",
    "mcp_client_version",
    "mcp_config_path",
    "normalize_call_result",
    "normalize_server_specs",
    "server_spec_to_value",
]
