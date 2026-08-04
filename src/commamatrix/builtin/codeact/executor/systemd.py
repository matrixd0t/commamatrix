# builtin/codeact/executor/systemd.py

"""Systemd execution backend — reserved for service-lifecycle-isolated CodeAct."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .backend import ExecutionBackend, ExecutionResult

if TYPE_CHECKING:
    from ....components.hook import BeforeToolCallCtx


class SystemdBackend(ExecutionBackend):
    """Reserved for service-lifecycle-isolated CodeAct execution."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def environment_description(self) -> str:
        return (
            "Your code runs in a service-managed isolated sandbox. "
            "Filesystem and network access are restricted by systemd service policies. "
            "Each execution starts with a clean namespace."
        )

    async def execute(self, code: str, ctx: BeforeToolCallCtx) -> ExecutionResult:
        raise NotImplementedError("Systemd CodeAct backend is not implemented yet")

    @staticmethod
    def is_available() -> bool:
        return False
