# builtin/codeact/tools.py

"""LLM-visible CodeAct tools: execute code, search and list available tools."""

from __future__ import annotations
from .manager import CodeActManager
from ...api.hooks import BeforeToolCallCtx
from ...api.tool import tool


@tool(codeact=True)
async def execute(code: str, ctx: BeforeToolCallCtx) -> str:
    """Execute Python code in the configured CodeAct environment."""
    runtime = ctx.run.agent.services.require(CodeActManager)
    result = await runtime.execute(code, ctx)
    return result.console_output()


@tool(codeact=True)
async def search_tools(query: str, ctx: BeforeToolCallCtx, limit: int = 5) -> str:
    """Semantically search for tools by description and signature."""
    runtime = ctx.run.agent.services.require(CodeActManager)
    results = runtime.searcher.search(query, limit=limit)
    if not results:
        return f"No tools found for query '{query}'."
    lines = [f"Search results for '{query}':"]
    for d in results:
        lines.append(f"  {d.namespace}.{d.name}")
        if d.doc:
            lines.append(f"    {d.doc}")
    return "\n".join(lines)


@tool(codeact=True)
async def list_tools(ctx: BeforeToolCallCtx, namespace: str | None = None) -> str:
    """List available tool namespaces or tools within a namespace."""
    runtime = ctx.run.agent.services.require(CodeActManager)
    searcher = runtime.searcher
    if namespace is None:
        lines = ["Available tool namespaces:"]
        for item in sorted(searcher.namespaces()):
            tools = searcher.tools(item)
            lines.append(f"  {item}  ({len(tools)} tools)")
        return "\n".join(lines)
    descriptors = searcher.tools(namespace)
    if not descriptors:
        return f"No tools found in namespace '{namespace}'."
    lines = [f"Tools in namespace '{namespace}':"]
    for d in descriptors:
        lines.append(f"  {d.name}")
        if d.doc:
            lines.append(f"    {d.doc}")
    return "\n".join(lines)
