# src/commamatrix/builtin/mcp/hooks.py

from __future__ import annotations

from ...components.hook import AfterToolCallCtx, after_tool_call
from .manager import MCPService


@after_tool_call
async def refresh_mcp_config_after_filesystem_tool(ctx: AfterToolCallCtx) -> None:
    """Reload MCP configuration after model-facing filesystem access."""
    descriptors = ctx.run.agent.tool_manager.descriptors
    if not any(descriptor.meta.get("filesystem") for descriptor in descriptors):
        return

    service = ctx.run.agent.services.get(MCPService)
    if service is not None:
        await service.refresh_if_changed()


__all__ = ["refresh_mcp_config_after_filesystem_tool"]
