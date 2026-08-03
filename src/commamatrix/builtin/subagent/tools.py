# builtin/subagent/tools.py

from __future__ import annotations

from ...components.hook import BeforeToolCallCtx
from ...components.tool import tool


@tool(alias="subagent", codeact=True)
async def call_agent(
    ctx: BeforeToolCallCtx,
    *,
    instructions: str | None = None,
    tools: str | None,
    continue_from_here: bool = False,
    wait_for_result: bool = True,
) -> str:
    """Run a headless subagent.

    instructions: use empty string for no system prompt, "all" to inherit your instructions, or provide a custom one.
    tools: use empty string for no tools,"all" for every tool, or a regex matching allowed tool names.
    If continue_from_here is true, inherit the current dialog history; otherwise start without it.
    If wait_for_result is true, return the subagent's response; otherwise start it in the background.
    """
    parent_item_id = ctx.run.state.get("child_parent_item_id")
    if continue_from_here and not isinstance(parent_item_id, int):
        raise ValueError("continue_from_here requires a tool call with a persisted parent item")

    result = await ctx.run.agent.submit_run(
        parent_item_id=parent_item_id if continue_from_here else None,
        instructions=instructions,
        tools=tools,
        wait_for_result=wait_for_result,
        user="agent",
        runner_namespace=f"subagent:{ctx.run.run_id}",
    )
    if not wait_for_result:
        return str(result)

    if result is None:
        return "Subagent run was aborted"
    return result.meta.get("internal_response") or result.final_answer or ""


__all__ = ["call_agent"]
