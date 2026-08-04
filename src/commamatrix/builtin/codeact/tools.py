# builtin/codeact/tools.py

"""LLM-visible CodeAct tools: execute code, search and list available tools."""

from __future__ import annotations
from .service import CodeActService, max_search_results, max_tools_list
from ...components.hook import BeforeToolCallCtx
from ...components.tool import ToolDescriptor, tool


def _format_tool_display(d: ToolDescriptor) -> str:
    parts = [f"# tools/{d.alias}" if d.alias else "# tools"]
    doc = d.doc or ""
    if doc.startswith("[ alias: "):
        _, _, doc = doc.partition("\n")
    if doc:
        parts.append(doc)
    return "\n".join(parts)


@tool(alias="", codeact=False)
async def execute(code: str, ctx: BeforeToolCallCtx) -> str:
    """Execute Python code in the configured CodeAct environment."""
    codeact: CodeActService = ctx.run.agent.services.require(CodeActService)
    result = await codeact.execute(code, ctx)
    return result.console_output()


@tool(alias="", codeact=False)
async def tool_search(query: str, ctx: BeforeToolCallCtx, limit: int = 5) -> str:
    """Semantically search for tools by description and signature."""
    codeact: CodeActService = ctx.run.agent.services.require(CodeActService)
    effective_limit = min(limit, codeact.config.get(max_search_results))
    results = codeact.searcher.search(query, limit=effective_limit)
    if not results:
        return f"No tools found for query '{query}'."
    return f"Search results for '{query}':\n" + "\n\n".join([_format_tool_display(d) for d in results])


@tool(alias="", codeact=False)
async def tools_list(ctx: BeforeToolCallCtx, alias: str | None = None, limit: int = 50) -> str:
    """List available tool names, grouped by and optionally filtered by alias."""
    codeact: CodeActService = ctx.run.agent.services.require(CodeActService)
    limit = min(limit, codeact.config.get(max_tools_list))
    tool_descriptors = codeact.searcher.descriptors
    if not tool_descriptors:
        return "No tools available."

    ungrouped: list[tuple[str, str]] = []
    grouped: dict[str, list[tuple[str, str]]] = {}
    for d in tool_descriptors:
        if d.alias:
            grouped.setdefault(d.alias, []).append((d.name, d.alias))
        else:
            ungrouped.append((d.name, d.alias))

    lines: list[str] = []
    for name, _ in ungrouped:
        lines.append(name)
    for grp_alias, members in grouped.items():
        if alias and grp_alias != alias:
            continue
        lines.append(grp_alias)
        for i, (name, _) in enumerate(members):
            connector = "└─" if i == len(members) - 1 else "├─"
            lines.append(f"{connector}{name}")

    if not lines:
        return "No tools found."

    visible_lines = lines[:limit]
    result = "\n".join(visible_lines)
    if len(lines) > limit:
        result += f"\n... and {len(lines) - limit} more tools"
    return result


