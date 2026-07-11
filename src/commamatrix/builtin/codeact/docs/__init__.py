# builtin/codeact/docs/__init__.py

from __future__ import annotations

from abc import ABC, abstractmethod

from ....api.tool import ToolDescriptor


class ToolDocBuilder(ABC):
    @abstractmethod
    def build(self, descriptor: ToolDescriptor) -> str:
        raise NotImplementedError
