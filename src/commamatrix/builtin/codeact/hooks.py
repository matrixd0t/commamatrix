# builtin/codeact/hooks.py

"""AgentLifecycle hooks for CodeAct — global kill switch and tool filtering."""

from __future__ import annotations

from ...components.config import ConfigField
from ...components.hook import (
    BeforeLlmCallCtx,
    before_llm_call,
)
from ...components.tool import ToolDescriptor
from .rpc.server import is_codeact_internal
from .service import CodeActService

codeact_enabled = ConfigField[bool](
    name="codeact.enabled",
    default=True,
    description="Global CodeAct switch. When False, all CodeAct tools are hidden.",
)


@before_llm_call
async def expose_codeact_tools(ctx: BeforeLlmCallCtx) -> None:
    """Filter tools based on CodeAct state."""
    codeact = ctx.run.agent.services.get(CodeActService)
    if codeact is None:
        return

    if not codeact.config.get(codeact_enabled):
        ctx.tools = [td for td in ctx.tools if not is_codeact_internal(td)]
        return

    ctx.tools = [t for t in ctx.tools if not is_codeact_internal(t)]
    codeact.rebuild_index(ctx.tools, ctx.run)
