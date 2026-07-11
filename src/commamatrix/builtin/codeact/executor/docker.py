# builtin/codeact/executor/docker.py

from __future__ import annotations

from typing import Any

from .backend import ExecutionBackend, ExecutionResult


class DockerBackend(ExecutionBackend):
    """Reserved for container-isolated CodeAct execution."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(self, code: str, ctx: object | None = None, namespace: dict[str, Any] | None = None) -> ExecutionResult:
        raise NotImplementedError
