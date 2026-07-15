# builtin/codeact/hooks.py

"""AgentLifecycle hooks for CodeAct — sets run flag, filters tools before LLM calls."""

from __future__ import annotations

from ...components.hook import BeforeLlmCallCtx, BeforeRunCtx, before_llm_call, before_run
from .manager import CodeActManager

CODACT_ENABLED_KEY = "codeact-enabled"
"""State key set on RunCtx.state when CodeAct is active for the current run."""


@before_run
def mark_codeact_enabled(ctx: BeforeRunCtx) -> None:
    ctx.run.state[CODACT_ENABLED_KEY] = True


@before_llm_call
async def expose_codeact_tools(ctx: BeforeLlmCallCtx) -> None:
    """Feed non-CodeAct tools into BM25 index; keep only CodeAct tools for the LLM."""
    if not ctx.run.state.get(CODACT_ENABLED_KEY):
        return

    runtime = ctx.run.agent.services.get(CodeActManager)
    if runtime is None:
        return

    indexed_tools = [t for t in ctx.tools if not t.metadata.get("codeact")]
    codeact_tools = [t for t in ctx.tools if t.metadata.get("codeact")]

    await runtime.rebuild(indexed_tools, ctx.run)
    ctx.tools = codeact_tools
