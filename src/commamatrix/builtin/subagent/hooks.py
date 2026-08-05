# builtin/subagent/hooks.py

from __future__ import annotations

from ...components.hook import BeforeLlmCallCtx, BeforeToolCallCtx, before_llm_call, before_tool_call
from ...components.instruction import InstructionCtx, instruction
from ...core.agent.agent import agent_by_name
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


@before_tool_call(priority=110)
async def prepare_subagent_call(ctx: BeforeToolCallCtx) -> None:
    """Validate continuation and pass the current tool item to the subagent tool."""
    descriptor = ctx.run.agent.tool_manager.resolve(ctx.tool_call.tool_name)
    if descriptor is None or descriptor.alias != "subagent" or descriptor.name != "call_subagent":
        return

    if not ctx.tool_call.tool_args.get("subagent"):
        ctx.tool_call.tool_args["subagent"] = ctx.run.agent.name

    continue_from_here = ctx.tool_call.tool_args.get("continue_from_here", False)
    parent_item_id = ctx.run.state.get("child_parent_item_id")
    if continue_from_here and not isinstance(parent_item_id, int):
        raise ValueError("continue_from_here requires a tool call with a persisted parent item")
    ctx.tool_call.tool_args["parent_item_id"] = parent_item_id if continue_from_here else None


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


@instruction(priority=-100)
def available_subagents(_ctx: InstructionCtx) -> str:
    """Describe the agents that can receive delegated work."""
    agents = sorted(agent_by_name.values(), key=lambda registered: registered.name)
    lines = ["# Subagents"]
    for registered in agents:
        lines.extend((f"## {registered.name}", registered.description))
    return "\n".join(lines)


__all__ = [
    "available_subagents",
    "enforce_allowed_tools",
    "filter_allowed_tools",
    "prepare_subagent_call",
]
