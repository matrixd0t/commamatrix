# src/commamatrix/builtin/mcp/instructions.py

from __future__ import annotations

from ...components.instruction import InstructionCtx, instruction
from .manager import MCPService


@instruction(priority=-170)
def mcp_config_context(ctx: InstructionCtx) -> str | None:
    """Tell filesystem-capable agents where MCP configuration is stored."""
    descriptors = ctx.run.agent.tool_manager.descriptors
    if not any(descriptor.meta.get("filesystem") for descriptor in descriptors):
        return None

    service = ctx.run.agent.services.get(MCPService)
    if service is None or not service.config_paths:
        return None

    paths = "\n".join(f"- {path}" for path in service.config_paths)
    return (
        "MCP server configuration is loaded from these files:\n"
        f"{paths}\n"
        "Edit these files to add or change MCP servers."
    )


__all__ = ["mcp_config_context"]
