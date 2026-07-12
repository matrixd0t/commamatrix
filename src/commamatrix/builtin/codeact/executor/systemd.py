# builtin/codeact/executor/systemd.py

"""Systemd execution backend — reserved for service-manager-isolated CodeAct."""

from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from .backend import ExecutionBackend, ExecutionResult

if TYPE_CHECKING:
    from ....api.hooks import BeforeToolCallCtx


class SystemdBackend(ExecutionBackend):
    """Reserved for service-manager-isolated CodeAct execution."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(
        self, code: str, ctx: BeforeToolCallCtx, namespace: dict[str, Any] | None = None
    ) -> ExecutionResult:
        raise NotImplementedError
