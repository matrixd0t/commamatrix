# builtin/codeact/executor/docker.py

"""Docker execution backend — reserved for container-isolated CodeAct."""

from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from .backend import ExecutionBackend, ExecutionResult

if TYPE_CHECKING:
    from ....components.hook import BeforeToolCallCtx


class DockerBackend(ExecutionBackend):
    """Reserved for container-isolated CodeAct execution."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(self, code: str, ctx: BeforeToolCallCtx, namespace: dict[str, Any] | None = None) -> ExecutionResult:
        raise NotImplementedError
