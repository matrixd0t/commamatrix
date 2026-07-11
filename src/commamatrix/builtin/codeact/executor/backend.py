# builtin/codeact/executor/backend.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExecutionResult:
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
    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, code: str, ctx: object | None = None, namespace: dict[str, Any] | None = None) -> ExecutionResult:
        raise NotImplementedError
