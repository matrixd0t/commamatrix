# builtin/codeact/service.py

"""CodeAct runtime — orchestrates code execution and nested tool invocation."""

from __future__ import annotations

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING, Any

from ...components.hook import BeforeToolCallCtx, RunCtx
from ...components.llm_adapter import ToolCall
from ...core.base.service import Service
from ...components.config import ConfigField
from .executor.backend import ExecutionBackend, ExecutionResult
from .executor.subprocess import SubprocessBackend
from .search.bm25 import BM25ToolSearcher

if TYPE_CHECKING:
    from ...components.tool import ToolDescriptor
    from ...core.agent import Agent


def _detect_backend() -> type[ExecutionBackend]:
    if sys.platform == "linux":
        from .executor.systemd import SystemdBackend
        return SystemdBackend
    if shutil.which("docker"):
        from .executor.docker import DockerBackend
        return DockerBackend
    return SubprocessBackend


backend_cls = ConfigField[type | None](
    name="codeact.backend",
    default=None,
    description="Execution backend class. Auto-detected if not set.",
)
searcher_cls = ConfigField[type](
    name="codeact.searcher",
    default=BM25ToolSearcher,
    description="Tool search engine class",
)


class CodeActService(Service):
    """Owns the execution backend, tool searcher, and nested tool gateway.

    Discovered automatically and added to an agent's services on next refresh.
    """

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        cls = self.config.get(backend_cls)
        self.backend = (cls or _detect_backend())()
        self.searcher = self.config.get(searcher_cls)()

    async def start(self) -> None:
        await self.backend.start()

    async def stop(self) -> None:
        await self.backend.stop()

    def rebuild(self, tools: list[ToolDescriptor], run: RunCtx) -> None:
        fingerprint = run.agent.tool_manager.fingerprint
        if fingerprint is not None:
            self.searcher.rebuild_index(fingerprint, tools)

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
