# builtin/codeact/search/api.py

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from ....api.tool import ToolDescriptor


class ToolSearcher(ABC):
    @abstractmethod
    def rebuild(self, fingerprint: str, descriptors: Iterable[ToolDescriptor]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, *, limit: int = 5) -> list[ToolDescriptor]:
        raise NotImplementedError

    @abstractmethod
    def namespaces(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def tools(self, namespace: str) -> list[ToolDescriptor]:
        raise NotImplementedError
