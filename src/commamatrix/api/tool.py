# api/tool.py

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, overload

from ..core.extension_runtime import ExtensionDescriptor, ExtensionSource

if TYPE_CHECKING:
    from .hooks import BeforeToolCallCtx

DEFAULT_TOOL_SEARCH_AMOUNT = 5
TOOL_ATTRIBUTE = "__commamatrix_tool__"
TOOL_MODULES: set[str] = set()


type AsyncOrSyncFunction = (Callable[..., object] | Callable[..., Awaitable[object]])
type Decorator[F: AsyncOrSyncFunction] = Callable[[F], F]


class ToolSource(ExtensionSource["ToolDescriptor"]):
    """
    Abstract source of tools.

    Each source is responsible for:
        - Discovering available tools via ``scan()``.
        - Executing its own tools via ``invoke()``.
    """

    @abstractmethod
    def scan(self) -> Iterable[ToolDescriptor]:
        raise NotImplementedError

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> object:
        """
        Execute the tool described by *descriptor* with the given *kwargs*.

        *ctx* provides runtime access to the ``RunCtx``, ``ToolCall``,
        and ``Agent``.  Subclasses that support type-based injection
        should inspect the tool function's signature and inject
        ``BeforeToolCallCtx`` parameters automatically.

        Must be overridden by subclasses.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ToolDescriptor(ExtensionDescriptor):
    """
    Immutable description of a tool, independent of its origin.

    Fields:
        id:  Globally unique identifier (e.g. ``python://ns/name``).
        namespace:  Logical grouping (typically the Python module name).
        alias:  Short name for virtual imports (defaults to namespace).
        name:  Tool function name.
        doc:  Human-readable description (used for search).
        schema:  JSON Schema of the tool's parameters.
        metadata:  Source-specific declarative metadata.
    """

    namespace: str
    alias: str
    name: str

    doc: str
    schema: dict[str, Any]

    metadata: dict[str, Any]

    def _fingerprint_payload(self) -> dict[str, Any]:
        """
        Metadata is declarative and participates in the semantic fingerprint.
        """
        meta = self.metadata
        return {
            "id": self.id,
            "namespace": self.namespace,
            "alias": self.alias,
            "name": self.name,
            "doc": self.doc,
            "schema": self.schema,
            "metadata": meta,
        }


@overload
def tool(fn: AsyncOrSyncFunction) -> AsyncOrSyncFunction:
    ...


@overload
def tool(**metadata: Any) -> Decorator:
    ...


def tool(arg: AsyncOrSyncFunction | None = None, **meta: Any):
    """
    Mark a function as a tool.

    The decorator does NOT register the tool — it only stamps the
    function with ``TOOL_ATTRIBUTE`` metadata and records its module
    in ``TOOL_MODULES``.  Actual registration happens when a
    ``PythonToolSource`` scans those modules.

    @tool
    def my_tool(x: int) -> int: ...

    @tool(version=2)
    def my_tool(x: int) -> int: ...
    """

    def decorate(fn: AsyncOrSyncFunction, metadata: dict[str, Any]):
        setattr(fn, TOOL_ATTRIBUTE, metadata)
        TOOL_MODULES.add(fn.__module__)
        return fn

    if arg is not None:
        return decorate(arg, {})

    return lambda fn: decorate(fn, meta)
