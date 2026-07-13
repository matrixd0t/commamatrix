# builtin/codeact/manager.py

"""CodeAct runtime — orchestrates code execution and nested tool invocation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .executor.backend import ExecutionBackend, ExecutionResult
from .search.api import ToolSearcher
from ...api.hooks import BeforeToolCallCtx
from ...api.llm_adapter import ToolCall

if TYPE_CHECKING:
    from ...api.hooks import RunCtx
    from ...api.tool import ToolDescriptor


class CodeActManager:
    """Owns the execution backend, tool searcher, and nested tool gateway.

    Registered as an agent service during ``on_agent_start``.
    """

    def __init__(self, backend: ExecutionBackend, searcher: ToolSearcher) -> None:
        self.backend = backend
        self.searcher = searcher

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
