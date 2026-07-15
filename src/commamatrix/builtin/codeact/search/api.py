# builtin/codeact/search/api.py

"""Abstract interface for tool search engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from ....components.tool import ToolDescriptor


class ToolSearcher(ABC):
    """Semantic search index over tool descriptors.

    Implementations rebuild their index when the tool fingerprint changes
    and return ranked results for a free-text query.
    """

    @abstractmethod
    def rebuild_index(self, fingerprint: str, descriptors: Iterable[ToolDescriptor]) -> None:
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
