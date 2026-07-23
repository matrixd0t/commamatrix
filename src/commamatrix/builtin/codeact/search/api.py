# builtin/codeact/search/api.py

"""Abstract interface for tool search engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from ....components.tool import ToolDescriptor


class ToolSearcher(ABC):
    """Semantic search index over tool descriptors.

    Implementations rebuild their index when the tool fingerprint changes
    and return ranked results for a free-content query.

    All public methods (rebuild_index, search, aliases, tools) are
    intentionally synchronous — CodeAct does not offload searcher
    operations to threads or executors.  The searcher runs directly
    on the event loop inside async wrappers (e.g. hooks.py,
    tools.py).  Each implementation is responsible for its own
    performance characteristics; a searcher backed by an external
    service may use its own transport internally.

    To avoid blocking the event loop for extended periods,
    keep the number of indexed descriptors modest, or use a
    searcher implementation that delegates to an external store.
    """

    @abstractmethod
    def rebuild_index(self, fingerprint: str, descriptors: Iterable[ToolDescriptor]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, *, limit: int = 5) -> list[ToolDescriptor]:
        raise NotImplementedError

    @abstractmethod
    def aliases(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def tools(self, alias: str) -> list[ToolDescriptor]:
        raise NotImplementedError

    @property
    @abstractmethod
    def descriptors(self) -> list[ToolDescriptor]:
        raise NotImplementedError
