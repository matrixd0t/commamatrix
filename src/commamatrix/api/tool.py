# api/tool.py

from __future__ import annotations

from abc import ABC
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, overload

from ..extensions import ExtensionDescriptor, ExtensionSource

if TYPE_CHECKING:
    from .hooks import BeforeToolCallCtx

DEFAULT_TOOL_SEARCH_AMOUNT = 5
TOOL_ATTRIBUTE = "__commamatrix_tool__"


type AsyncOrSyncFunction = Callable[..., object] | Callable[..., Awaitable[object]]
type Decorator[F: AsyncOrSyncFunction] = Callable[[F], F]


@dataclass(frozen=True, slots=True)
class ToolDescriptor(ExtensionDescriptor):
    """Immutable description of a tool, independent of its origin."""

    namespace: str
    alias: str
    name: str
    exported_name: str

    doc: str
    schema: dict[str, Any]

    metadata: dict[str, Any]

    def _fingerprint_payload(self) -> dict[str, Any]:
        meta = self.metadata
        return {
            "id": self.id,
            "namespace": self.namespace,
            "alias": self.alias,
            "name": self.name,
            "exported_name": self.exported_name,
            "doc": self.doc,
            "schema": self.schema,
            "metadata": meta,
        }


class ToolSource(ExtensionSource[ToolDescriptor], ABC):
    """Abstract source of tools.

    Each source is responsible for discovering available tools via scan()
    and executing its own tools via invoke().
    """

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> object:
        """Execute the tool described by descriptor with the given kwargs.

        ctx provides runtime access to RunCtx, ToolCall, and Agent.
        Subclasses that support type-based injection should inspect the
        tool function's signature and inject BeforeToolCallCtx parameters
        automatically.
        Must be overridden by subclasses.
        """
        raise NotImplementedError


@overload
def tool(fn: AsyncOrSyncFunction) -> AsyncOrSyncFunction: ...
@overload
def tool(**metadata: Any) -> Decorator: ...


def tool(arg: AsyncOrSyncFunction | None = None, **meta: Any):
    """Mark a function as a tool.

    Stamps the function with TOOL_ATTRIBUTE metadata.
    """

    def decorate(fn: AsyncOrSyncFunction, metadata: dict[str, Any]):
        setattr(fn, TOOL_ATTRIBUTE, metadata)
        return fn

    if arg is not None:
        return decorate(arg, {})

    return lambda fn: decorate(fn, meta)
