# builtin/codeact/tools.py

"""LLM-visible CodeAct tools: execute code, search and list available tools."""

from __future__ import annotations
from .service import CodeActService
from ...components.hook import BeforeToolCallCtx
from ...components.tool import tool


@tool(alias="codeact", codeact=True)
async def execute(code: str, ctx: BeforeToolCallCtx) -> str:
    """Execute Python code in the configured CodeAct environment."""
    codeact: CodeActService = ctx.run.agent.services.require(CodeActService)
    result = await codeact.execute(code, ctx)
    return result.console_output()


@tool(alias="codeact", codeact=True)
async def search_tools(query: str, ctx: BeforeToolCallCtx, limit: int = 5) -> str:
    """Semantically search for tools by description and signature."""
    codeact: CodeActService = ctx.run.agent.services.require(CodeActService)
    results = codeact.searcher.search(query, limit=limit)
    if not results:
        return f"No tools found for query '{query}'."
    tm = ctx.run.agent.tool_manager
    lines = [f"Search results for '{query}':"]
    for d in results:
        lines.append(f"  {tm.public_name(d)}")
        if d.doc:
            lines.append(f"    {d.doc}")
    return "\n".join(lines)


@tool(alias="codeact", codeact=True)
async def list_tools(ctx: BeforeToolCallCtx, alias: str | None = None) -> str:
    """List available tool aliases or tools within an alias."""
    codeact: CodeActService = ctx.run.agent.services.require(CodeActService)
    searcher = codeact.searcher
    tm = ctx.run.agent.tool_manager
    if alias is None:
        lines = ["Available tool aliases:"]
        for item in sorted(searcher.aliases()):
            tools = searcher.tools(item)
            lines.append(f"  {item}  ({len(tools)} tools)")
        return "\n".join(lines)
    descriptors = searcher.tools(alias)
    if not descriptors:
        return f"No tools found for alias '{alias}'."
    lines = [f"Tools in alias '{alias}':"]
    for d in descriptors:
        lines.append(f"  {tm.public_name(d)}")
        if d.doc:
            lines.append(f"    {d.doc}")
    return "\n".join(lines)
