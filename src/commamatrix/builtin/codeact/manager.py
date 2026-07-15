# builtin/codeact/manager.py

"""CodeAct runtime — orchestrates code execution and nested tool invocation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .executor.backend import ExecutionResult
from ...components.hook import BeforeToolCallCtx, RunCtx
from ...components.llm_adapter import ToolCall
from ...core.base.service import Service
from ...components.config import Config

if TYPE_CHECKING:
    from ...components.tool import ToolDescriptor


class CodeActManager(Service):
    """Owns the execution backend, tool searcher, and nested tool gateway.

    Discovered automatically as a AbstractService when the codeact package is
    imported and added to an agent's extension scope.
    """

    def __init__(self, config: Config, **kwargs: Any) -> None:
        super().__init__()
        from .executor.subprocess import SubprocessBackend
        from .search.bm25 import BM25ToolSearcher
        self.backend = kwargs.get('backend') or SubprocessBackend()
        self.searcher = kwargs.get('searcher') or BM25ToolSearcher()

    async def start(self) -> None:
        await self.backend.start()

    async def stop(self) -> None:
        await self.backend.stop()

    async def rebuild(self, tools: list[ToolDescriptor], run: RunCtx) -> None:
        fingerprint = run.agent.tool_manager.fingerprint
        if fingerprint is not None:
            self.searcher.rebuild(fingerprint, tools)

    async def execute(self, code: str, ctx: BeforeToolCallCtx) -> ExecutionResult:
        return await self.backend.execute(code, ctx, namespace={'__name__': '__codeact__'})

    @staticmethod
    async def invoke_tool(ctx: BeforeToolCallCtx, tool_call: ToolCall) -> Any:
        """Invoke a nested tool through the agent's unified tool lifecycle.

        Delegates to ``Agent._run_tool_lifecycle()`` which handles
        BEFORE_TOOL_CALL / AFTER_TOOL_CALL hooks and tool execution.
        Returns the raw Python result (not serialized).
        """
        _, result = await ctx.run.agent._run_tool_lifecycle(ctx.run, tool_call)
        return result.content
