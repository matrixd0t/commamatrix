# builtin/codeact/hooks.py

from __future__ import annotations

from ...api.hooks import OnAgentStartCtx, BeforeLlmCallCtx, on_agent_start, before_llm_call
from .executor.subprocess import SubprocessBackend
from .runtime import CodeActRuntime
from .search.bm25 import BM25ToolSearcher


@on_agent_start
async def install_codeact(ctx: OnAgentStartCtx) -> None:
    runtime = CodeActRuntime(backend=SubprocessBackend(), searcher=BM25ToolSearcher())
    await runtime.start()
    ctx.agent.services[CodeActRuntime] = runtime


@before_llm_call
async def expose_codeact_tools(ctx: BeforeLlmCallCtx) -> None:
    runtime = ctx.run.agent.services.get(CodeActRuntime)
    if runtime is None:
        return

    indexed_tools = [t for t in ctx.tools if not t.metadata.get("codeact")]
    codeact_tools = [t for t in ctx.tools if t.metadata.get("codeact")]

    await runtime.rebuild(indexed_tools, ctx.run)
    ctx.tools = codeact_tools
