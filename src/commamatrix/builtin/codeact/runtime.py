# builtin/codeact/runtime.py

"""CodeAct runtime — orchestrates code execution and nested tool invocation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .executor.backend import ExecutionBackend, ExecutionResult
from .search.api import ToolSearcher
from ...api.hooks import AfterToolCallCtx, BeforeToolCallCtx, HookEventType
from ...api.llm_adapter import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from ...api.hooks import RunCtx
    from ...api.tool import ToolDescriptor


class CodeActRuntime:
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
    async def invoke_tool(ctx: BeforeToolCallCtx, name: str, args: dict[str, Any]) -> Any:
        """Invoke a nested tool through the normal hook and policy lifecycle."""
        tool_call = ToolCall(tool_call_id=uuid4().hex, tool_name=name, tool_args=args)
        before_ctx = BeforeToolCallCtx(run=ctx.run, tool_call=tool_call)
        await ctx.run.agent.hook_manager.fire(HookEventType.BEFORE_TOOL_CALL.value, before_ctx)
        tool_call = before_ctx.tool_call

        if before_ctx.abort_tool_call:
            result = ToolCallResult.aborted(tool_call.tool_call_id, before_ctx.abort_reason)
            after_ctx = AfterToolCallCtx(run=ctx.run, tool_call=tool_call, result=result)
            await ctx.run.agent.hook_manager.fire(HookEventType.AFTER_TOOL_CALL.value, after_ctx)
            return after_ctx.result.content

        raw_result: Any = None
        succeeded = False
        try:
            descriptor = ctx.run.agent.tool_manager.resolve(tool_call.tool_name)
            if descriptor is None:
                raise LookupError(f'Tool not found: {tool_call.tool_name!r}')
            raw_result = await ctx.run.agent.tool_manager.invoke(
                descriptor, tool_call.tool_args, ctx=before_ctx,
            )
            content = raw_result if isinstance(raw_result, str) else json.dumps(
                raw_result, ensure_ascii=False, default=str,
            )
            result = ToolCallResult(tool_call_id=tool_call.tool_call_id, content=content)
            succeeded = True
        except Exception as exc:
            result = ToolCallResult(
                tool_call_id=tool_call.tool_call_id,
                content=f'Error executing tool {tool_call.tool_name!r}: {exc}',
            )

        after_ctx = AfterToolCallCtx(run=ctx.run, tool_call=tool_call, result=result)
        await ctx.run.agent.hook_manager.fire(HookEventType.AFTER_TOOL_CALL.value, after_ctx)
        if not succeeded or after_ctx.result.content != result.content:
            return after_ctx.result.content
        return raw_result
