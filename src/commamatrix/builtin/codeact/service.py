# builtin/codeact/service.py

"""CodeAct runtime — orchestrates code execution and nested tool invocation."""

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING, Any

from ...components.hook import BeforeToolCallCtx, RunCtx
from ...components.llm_adapter import ToolCall
from ...core.classes.service import Service
from ...components.config import ConfigField
from .executor.backend import ExecutionBackend, ExecutionResult
from .executor.subproc import SubprocessBackend
from .search.bm25 import BM25ToolSearcher

if TYPE_CHECKING:
    from ...components.tool import ToolDescriptor
    from ...core.agent import Agent


def _detect_backend() -> type[ExecutionBackend]:
    candidates: list[type[ExecutionBackend]] = []
    if sys.platform == "linux":
        from .executor.systemd import SystemdBackend

        candidates.append(SystemdBackend)
    if shutil.which("docker"):
        from .executor.docker import DockerBackend

        candidates.append(DockerBackend)
    for cls in candidates:
        if cls.is_available():
            return cls
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
execution_timeout = ConfigField[float](
    name="codeact.execution_timeout",
    default=30.0,
    description="Timeout in seconds for a single code execution",
)
rpc_timeout = ConfigField[float](
    name="codeact.rpc_timeout",
    default=10.0,
    description="Timeout in seconds for a single RPC tool call",
)
shutdown_timeout = ConfigField[float](
    name="codeact.shutdown_timeout",
    default=5.0,
    description="Grace period in seconds for worker shutdown",
)
max_output_bytes = ConfigField[int](
    name="codeact.max_output_bytes",
    default=1_000_000,
    description="Maximum bytes of stdout/stderr captured per execution",
)
max_search_results = ConfigField[int](
    name="codeact.max_search_results",
    default=5,
    description="Maximum number of tools shown in search_tools results",
)
max_list_tools = ConfigField[int](
    name="codeact.max_list_tools",
    default=50,
    description="Maximum number of tools shown in list_tools output",
)

CODEACT_NESTED_TOOL_KEY = "codeact_nested_tool"


class CodeActService(Service):
    """Owns the execution backend, tool searcher, and nested tool gateway.

    The execution backend is fully async — it manages subprocesses,
    pipes, and I/O.  The tool searcher (``ToolSearcher`` subclass) is
    intentionally synchronous and runs directly on the event loop;
    CodeAct does not offload searcher operations to threads.

    Discovered automatically and added to an agent's services on next refresh.
    """

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        cls = self.config.get(backend_cls)
        backend_cls_resolved = cls or _detect_backend()
        if backend_cls_resolved is SubprocessBackend:
            self.backend = SubprocessBackend(
                execution_timeout=self.config.get(execution_timeout),
                shutdown_timeout=self.config.get(shutdown_timeout),
                max_output_bytes=self.config.get(max_output_bytes),
                rpc_timeout=self.config.get(rpc_timeout),
            )
        else:
            self.backend = backend_cls_resolved()
        self.searcher = self.config.get(searcher_cls)()

    async def start(self) -> None:
        await self.backend.start()

    async def stop(self) -> None:
        await self.backend.stop()

    def rebuild_index(self, tools: list[ToolDescriptor], run: RunCtx) -> None:
        fingerprint = run.agent.tool_manager.fingerprint
        if fingerprint is not None:
            self.searcher.rebuild_index(fingerprint, tools)

    async def execute(self, code: str, ctx: BeforeToolCallCtx) -> ExecutionResult:
        return await self.backend.execute(code, ctx)

    async def invoke_tool(self, ctx: BeforeToolCallCtx, tool_call: ToolCall) -> Any:
        """Invoke a nested tool through the agent's unified tool lifecycle.

        Delegates to ``Agent._run_tool_lifecycle()`` which handles
        BEFORE_TOOL_CALL / AFTER_TOOL_CALL hooks and tool execution.
        Returns the raw Python result (not serialized).
        """
        _, result = await ctx.run.agent._run_tool_lifecycle(
            ctx.run,
            tool_call,
            persist_result=False,
            tool_meta={CODEACT_NESTED_TOOL_KEY: True},
        )
        return result.content
