# builtin/codeact/context.py

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.tool_runtime import ToolRuntime
    from .search.api import ToolSearcher
    from .executor.backend import ExecutionBackend


class CodeActContext:
    def __init__(
        self,
        backend: ExecutionBackend,
        searcher: ToolSearcher,
        runtime: ToolRuntime,
    ) -> None:
        self.backend = backend
        self.searcher = searcher
        self.runtime = runtime
