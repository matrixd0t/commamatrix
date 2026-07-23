# builtin/codeact/executor/docker.py

"""Docker execution backend — reserved for container-isolated CodeAct."""

from __future__ import annotations

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

    def environment_description(self) -> str:
        return "Your code runs in an isolated Docker container with restricted filesystem and network access."

    async def execute(self, code: str, ctx: BeforeToolCallCtx) -> ExecutionResult:
        raise NotImplementedError("Docker CodeAct backend is not implemented yet")

    @staticmethod
    def is_available() -> bool:
        return False
