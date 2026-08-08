# builtin/codeact/instructions.py

"""CodeAct instruction — injects environment info and available tools into system prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...components.instruction import InstructionCtx, instruction
from .hooks import codeact_enabled
from .rpc.server import is_codeact_internal

if TYPE_CHECKING:
    from .service import CodeActService


def _format_codeact_guide(codeact: CodeActService) -> str:
    lines = [
        "# CodeAct mode",
        "You have access to an `execute` tool that runs Python code on the backend.",
        "Inside execute(), import tools as async functions: `import tools.<name> as <name>`.",
        "All tools are async — top-level await is allowed.",
        "You MUST prioritize tools over other methods when doing stuff. Example: prefer `write` tool instead of open().write() when you need to store downloaded JSON.",
        "Use `tool_search(query)` to find tools by description.",
        "Use `tools_list()` to list available tools.",
        "Take advantage of tool parallelization and chaining capabilities.",
        "",
        codeact.backend.environment_description(),
    ]
    return "\n".join(lines)


@instruction(priority=-100)
def codeact_guide(ctx: InstructionCtx) -> str | None:
    """Return CodeAct environment info and available tools for the system prompt."""
    from .service import CodeActService

    codeact = ctx.run.agent.services.get(CodeActService)
    if codeact is None:
        return None
    if not codeact.config.get(codeact_enabled):
        return None

    if not codeact.searcher.descriptors:
        all_tools = ctx.run.agent.tool_manager.descriptors
        index_tools = [t for t in all_tools if not is_codeact_internal(t)]
        codeact.rebuild_index(index_tools, ctx.run)

    return _format_codeact_guide(codeact)
