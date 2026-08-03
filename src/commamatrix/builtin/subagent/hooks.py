# builtin/subagent/hooks.py

from __future__ import annotations

from ...components.hook import BeforeLlmCallCtx, BeforeToolCallCtx, before_llm_call, before_tool_call
from .policy import filter_tool_descriptors, is_tool_allowed


@before_llm_call(priority=100)
async def filter_allowed_tools(ctx: BeforeLlmCallCtx) -> None:
    """Limit model-visible tools while retaining CodeAct control tools."""
    allowed = filter_tool_descriptors(
        ctx.run,
        [descriptor for descriptor in ctx.tools if descriptor.meta.get("codeact", True)],
    )
    allowed_ids = {descriptor.id for descriptor in allowed}
    ctx.tools = [
        descriptor
        for descriptor in ctx.tools
        if descriptor.meta.get("codeact", True) is False
        or descriptor.id in allowed_ids
    ]


@before_tool_call(priority=100)
async def enforce_allowed_tools(ctx: BeforeToolCallCtx) -> None:
    """Reject direct and nested calls outside the current tool policy."""
    descriptor = ctx.run.agent.tool_manager.resolve(ctx.tool_call.tool_name)
    if descriptor is None or descriptor.meta.get("codeact", True) is False:
        return
    public_name = ctx.run.agent.tool_manager.public_name(descriptor)
    if not is_tool_allowed(ctx.run, public_name):
        ctx.abort_tool_call = True
        ctx.abort_reason = f"Tool {public_name!r} is not allowed in this run"


__all__ = ["enforce_allowed_tools", "filter_allowed_tools"]
