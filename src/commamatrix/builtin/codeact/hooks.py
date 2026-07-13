# builtin/codeact/hooks.py

"""Lifecycle hooks that install CodeAct on agent start and filter tools before LLM calls."""

from __future__ import annotations

from ...api.hooks import OnAgentStartCtx, BeforeLlmCallCtx, on_agent_start, before_llm_call
from .executor.subprocess import SubprocessBackend
from .manager import CodeActManager
from .search.bm25 import BM25ToolSearcher


@on_agent_start
async def install_codeact(ctx: OnAgentStartCtx) -> None:
    """Create and register the CodeAct manager as an agent service."""
    manager = CodeActManager(backend=SubprocessBackend(), searcher=BM25ToolSearcher())
    await manager.start()
    ctx.agent.services[CodeActManager] = manager
    ctx.agent.tool_manager.scan()
    ctx.agent.hook_manager.scan()


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
