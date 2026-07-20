# builtin/codeact/hooks.py

"""AgentLifecycle hooks for CodeAct — sets run flag, filters tools before LLM calls."""

from __future__ import annotations

from ...components.config import ConfigField
from ...components.hook import BeforeLlmCallCtx, BeforeRunCtx, before_llm_call, before_run
from .service import CodeActService

CODEACT_ENABLED_KEY = "codeact-enabled"
"""State key set on RunCtx.state when CodeAct is active for the current run."""

codeact_enabled = ConfigField[bool](
    name="codeact.enabled",
    default=True,
    description="Enable CodeAct for all runs by default",
)


@before_run
def mark_codeact_enabled(ctx: BeforeRunCtx) -> None:
    if CODEACT_ENABLED_KEY not in ctx.run.state:
        codeact = ctx.run.agent.services.get(CodeActService)
        if codeact is not None:
            ctx.run.state[CODEACT_ENABLED_KEY] = codeact.config.get(codeact_enabled)
        else:
            ctx.run.state[CODEACT_ENABLED_KEY] = True


@before_llm_call
async def expose_codeact_tools(ctx: BeforeLlmCallCtx) -> None:
    """Feed non-CodeAct tools into BM25 index; keep only CodeAct tools for the LLM."""
    if not ctx.run.state.get(CODEACT_ENABLED_KEY):
        return

    codeact = ctx.run.agent.services.get(CodeActService)
    if codeact is None:
        return

    codeact_tools, non_codeact_tools = [], []
    for t in ctx.tools:
        codeact_tools.append(t) if t.meta.get("codeact") else non_codeact_tools.append(t)

    codeact.rebuild_index(non_codeact_tools, ctx.run)
    ctx.tools = codeact_tools
