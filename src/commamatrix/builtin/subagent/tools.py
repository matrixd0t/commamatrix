# builtin/subagent/tools.py

from __future__ import annotations

from ...components.config import _MISSING
from ...components.tool import tool
from ...core.agent.agent import get_subagent_by_name


@tool(alias="", codeact=True)
async def call_subagent(
    subagent: str = "",
    *,
    instructions: str | None = _MISSING,
    tools: str | None,
    continue_from_here: bool = False,
    parent_item_id: int | None = None,
    wait_for_result: bool = True,
) -> str:
    """Run a headless subagent.

    subagent: name of the registered agent that should execute the run. If the name is unknown, leave it empty to run in the current agent.
    instructions: omit to use aggregated instructions, use empty string or null to disable them, or provide a custom system input.
    tools: use empty string for no tools, "all" for every tool, or a regex matching allowed tool names.
    If continue_from_here is true, inherit the current dialog history; otherwise start without it.
    If wait_for_result is true, return the subagent's response; otherwise start it in the background.
    """
    target = get_subagent_by_name(subagent)
    result = await target.submit_run(
        parent_item_id=parent_item_id if continue_from_here else None,
        instructions=instructions,
        tools=tools,
        wait_for_result=wait_for_result,
        user="agent",
    )
    if not wait_for_result:
        return str(result)

    if result is None:
        return "Subagent run was aborted"
    return result.meta.get("internal_response") or result.final_answer or ""


__all__ = ["call_subagent"]
