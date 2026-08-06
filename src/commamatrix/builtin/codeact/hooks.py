# builtin/codeact/hooks.py

"""AgentLifecycle hooks for CodeAct — global kill switch and tool filtering."""

from __future__ import annotations

from ...components.config import ConfigField
from ...components.hook import (
    BeforeLlmCallCtx,
    before_llm_call,
)
from .rpc.server import is_codeact_internal
from .service import CodeActService

codeact_enabled = ConfigField[bool](
    name="codeact_enabled",
    default=True,
    description="Global CodeAct switch. When True, only CodeAct tools are shown to the LLM and the rest are indexed for BM25 search. When False, CodeAct tools are hidden.",
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

    non_codeact = [t for t in ctx.tools if not is_codeact_internal(t)]
    codeact.rebuild_index(non_codeact, ctx.run)
    ctx.tools = [t for t in ctx.tools if is_codeact_internal(t)]
