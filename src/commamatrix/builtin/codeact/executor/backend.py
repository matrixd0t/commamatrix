# builtin/codeact/executor/backend.py

"""Abstract execution backend and result dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ....components.hook import BeforeToolCallCtx


@dataclass(slots=True)
class ExecutionResult:
    """Output of a single code execution: stdout, stderr, return code and timing."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    duration_ms: float | None = None

    def console_output(self) -> str:
        parts: list[str] = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"stderr:\n{self.stderr}")
        if self.returncode:
            parts.append(f"exit code: {self.returncode}")
        if self.duration_ms is not None:
            parts.append(f"({self.duration_ms:.0f}ms)")
        return "\n".join(parts)


class ExecutionBackend(ABC):
    """
    Runs code and returns captured output.

    Unlike ToolSearcher, ExecutionBackend methods are async because
    they manage child processes, pipes, sockets, or containers —
    all inherently async I/O operations.  start / stop / execute
    are expected to be truly asynchronous and must not rely on
    ``to_thread`` or similar thread-offloading primitives.

    Implementations may range from a local subprocess to a container
    or service-manager-isolated environment.
    """

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, code: str, ctx: BeforeToolCallCtx, namespace: dict[str, Any] | None = None) -> ExecutionResult:
        raise NotImplementedError

    @staticmethod
    def is_available() -> bool:
        """Override to report whether this backend can be used."""
        return True
