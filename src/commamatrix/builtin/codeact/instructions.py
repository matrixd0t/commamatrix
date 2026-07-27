# builtin/codeact/instructions.py

"""CodeAct instruction — injects environment info and available tools into system prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...components.instruction import InstructionCtx, instruction
from ...components.config import ConfigField
from .rpc.server import is_codeact_internal

if TYPE_CHECKING:
    from .service import CodeActService

codeact_guide_visible = ConfigField[bool](
    name="codeact.guide_visible",
    default=True,
    description="When True, inject CodeAct environment and tool listing into system prompt.",
)


def _format_codeact_guide(codeact: CodeActService) -> str:
    lines = [
        "# CodeAct mode",
        "",
        "You have access to an `execute` tool that runs Python code on the backend.",
        "Inside execute(), import tools as async functions: `import tools.<name> as <name>`.",
        "All tools are async — top-level await is allowed.",
        "Use `search_tools(query)` to find tools by description.",
        "Use `list_tools()` to list available tools.",
        "Take advantage of tool parallelization and chaining capabilities.",
        "",
        codeact.backend.environment_description(),
        "",
        "Available tools:",
    ]

    descriptors = codeact.searcher.descriptors
    grouped: dict[str, list[str]] = {}
    ungrouped: list[str] = []
    for d in descriptors:
        if d.alias:
            grouped.setdefault(d.alias, []).append(d.name)
        else:
            ungrouped.append(d.name)

    for name in ungrouped:
        lines.append(name)
    for grp_alias, members in grouped.items():
        lines.append(grp_alias)
        for i, name in enumerate(members):
            connector = "└─" if i == len(members) - 1 else "├─"
            lines.append(f"{connector}{name}")

    return "\n".join(lines)


@instruction(priority=-100)
def codeact_guide(ctx: InstructionCtx) -> str | None:
    """Return CodeAct environment info and available tools for the system prompt."""
    from .service import CodeActService

    codeact = ctx.run.agent.services.get(CodeActService)
    if codeact is None:
        return None
    if not codeact.config.get(codeact_guide_visible):
        return None

    if not codeact.searcher.descriptors:
        all_tools = ctx.run.agent.tool_manager.descriptors
        index_tools = [t for t in all_tools if not is_codeact_internal(t)]
        codeact.rebuild_index(index_tools, ctx.run)

    return _format_codeact_guide(codeact)
