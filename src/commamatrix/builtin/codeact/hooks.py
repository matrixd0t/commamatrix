# builtin/codeact/hooks.py

"""Lifecycle hooks for CodeAct — filters tools before LLM calls."""

from __future__ import annotations

from ...api.hooks import BeforeLlmCallCtx, before_llm_call
from .manager import CodeActManager


@before_llm_call
async def expose_codeact_tools(ctx: BeforeLlmCallCtx) -> None:
    """Feed non-CodeAct tools into BM25 index; keep only CodeAct tools for the LLM."""
    runtime = ctx.run.agent.services.get(CodeActManager)
    if runtime is None:
        return

    indexed_tools = [t for t in ctx.tools if not t.metadata.get("codeact")]
    codeact_tools = [t for t in ctx.tools if t.metadata.get("codeact")]

    await runtime.rebuild(indexed_tools, ctx.run)
    ctx.tools = codeact_tools
