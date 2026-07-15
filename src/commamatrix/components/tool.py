# components/tool.py

from __future__ import annotations

import functools
import inspect
import weakref
from abc import ABC
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, get_type_hints, overload

from matrix_fn_schema import build_json_schema

from ..core.base.descriptor import Descriptor
from ..core.base.source import Source
from ..core.base.manager import Manager
from ..core.base.source import PythonSource
from .llm_adapter import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from .hook import BeforeToolCallCtx

DEFAULT_TOOL_SEARCH_AMOUNT = 5
TOOL_ATTRIBUTE = "__commamatrix_tool__"

type AsyncOrSyncFunction = Callable[..., object] | Callable[..., Awaitable[object]]
type Decorator[F: AsyncOrSyncFunction] = Callable[[F], F]


@dataclass(frozen=True, slots=True)
class ToolDescriptor(Descriptor):
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
            "meta": meta,
        }


class ToolSource(Source[ToolDescriptor], ABC):
    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> object:
        raise NotImplementedError


@overload
def tool(fn: AsyncOrSyncFunction) -> AsyncOrSyncFunction: ...
@overload
def tool(**metadata: Any) -> Decorator: ...


def tool(arg: AsyncOrSyncFunction | None = None, **meta: Any):
    def decorate(fn: AsyncOrSyncFunction, metadata: dict[str, Any]):
        setattr(fn, TOOL_ATTRIBUTE, metadata)
        return fn

    if arg is not None:
        return decorate(arg, {})

    return lambda fn: decorate(fn, meta)


class PythonToolSource(PythonSource[ToolDescriptor], ToolSource):
    def __init__(self) -> None:
        super().__init__()
        self._functions: dict[str, AsyncOrSyncFunction] = {}

    def scan(self) -> list[ToolDescriptor]:
        self._functions.clear()
        return cast(list[ToolDescriptor], list(super().scan()))

    @property
    def marker_attribute(self) -> str:
        return TOOL_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> ToolDescriptor | None:
        fn = cast(AsyncOrSyncFunction, obj)
        raw_meta: dict[str, Any] = getattr(fn, TOOL_ATTRIBUTE)
        metadata = dict(raw_meta)
        metadata['signature'] = _signature_metadata(fn)
        descriptor_id = f"python://{fn.__module__}/{object_name}"
        self._functions[descriptor_id] = fn

        namespace: str = fn.__module__
        alias: str = metadata.get('alias', namespace)
        alias_for_doc: str | None = metadata.get('alias')

        descriptor = ToolDescriptor(
            id=descriptor_id,
            namespace=namespace,
            alias=alias,
            name=object_name,
            exported_name=object_name,
            doc=self._build_doc(fn, alias=alias_for_doc),
            schema=build_json_schema(_schema_fn(fn)),
            metadata=metadata,
            _source_ref=weakref.ref(self),
        )
        return descriptor

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> object:
        fn = self._functions.get(descriptor.id)
        if fn is None:
            raise RuntimeError(f"Tool {descriptor.id} is not owned by this source")

        if ctx is not None:
            kwargs = _inject(fn, kwargs, ctx)

        if inspect.iscoroutinefunction(fn):
            return await fn(**kwargs)
        return fn(**kwargs)

    @staticmethod
    def _build_doc(fn: AsyncOrSyncFunction, alias: str | None = None) -> str:
        parts: list[str] = []
        if alias is not None:
            parts.append(f"[ alias: {alias} ]")

        prefix = "async " if inspect.iscoroutinefunction(fn) else ""
        parts.append(f"{prefix}def {fn.__name__}{inspect.signature(_schema_fn(fn))}:")
        parts.append('"""')
        parts.append(inspect.getdoc(fn) or "")
        parts.append('"""')
        return "\n".join(parts)


_INJECTABLE_TYPES: set[type] | None = None


def _get_injectable_types() -> set[type]:
    global _INJECTABLE_TYPES
    if _INJECTABLE_TYPES is None:
        from .hook import BeforeToolCallCtx as _BTC
        _INJECTABLE_TYPES = {_BTC}
    return _INJECTABLE_TYPES


def _is_injectable(annotation: Any) -> bool:
    return annotation in _get_injectable_types()


def _injectable_params(fn: AsyncOrSyncFunction) -> dict[str, type]:
    hints = _type_hints(fn)
    return {
        name: hints[name]
        for name, hint in hints.items()
        if _is_injectable(hint)
    }


def _schema_fn(fn: AsyncOrSyncFunction) -> AsyncOrSyncFunction:
    hints = _type_hints(fn)
    injectable = _injectable_params(fn)
    if not injectable:
        return fn

    sig = inspect.signature(fn)
    params = [p for name, p in sig.parameters.items() if name not in injectable]

    @functools.wraps(fn)
    def wrapper(**kwargs: Any) -> Any:
        pass

    wrapper.__signature__ = sig.replace(parameters=params)
    wrapper.__annotations__ = {k: v for k, v in hints.items() if k not in injectable}
    return wrapper


def _inject(fn: AsyncOrSyncFunction, kwargs: dict[str, Any], ctx: BeforeToolCallCtx) -> dict[str, Any]:
    injectable = _injectable_params(fn)
    result = dict(kwargs)
    for name, param_type in injectable.items():
        if param_type in _get_injectable_types():
            from .hook import BeforeToolCallCtx as _BTC
            if param_type is _BTC:
                result[name] = ctx
    return result


def _signature_metadata(fn: AsyncOrSyncFunction) -> list[dict[str, Any]]:
    hints = _type_hints(fn)
    injectable = _injectable_params(fn)
    result: list[dict[str, Any]] = []
    for name, parameter in inspect.signature(fn).parameters.items():
        if name in injectable:
            continue
        item: dict[str, Any] = {
            "name": name,
            "kind": parameter.kind.name,
            "annotation": getattr(
                hints.get(name), "__name__", str(hints.get(name, "Any"))
            ),
        }
        if parameter.default is not inspect.Parameter.empty:
            default = parameter.default
            item["default"] = (
                default
                if default is None or isinstance(default, (bool, int, float, str))
                else repr(default)
            )
        result.append(item)
    return result


def _type_hints(fn: AsyncOrSyncFunction) -> dict[str, Any]:
    try:
        return {k: v for k, v in get_type_hints(fn).items() if k != "return"}
    except Exception:
        return dict(getattr(fn, "__annotations__", {}))


class ToolManager(Manager[ToolDescriptor]):
    def __init__(self) -> None:
        super().__init__()
        self._python_source = PythonToolSource()
        self.mount(self._python_source)
        self._by_alias: dict[str, list[ToolDescriptor]] = {}
        self._by_name: dict[str, list[ToolDescriptor]] = {}
        self._by_exported_name: dict[str, list[ToolDescriptor]] = {}
        self._schemas: list[dict[str, Any]] = []

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    @property
    def fingerprint(self) -> str | None:
        return self._fingerprint

    def schemas(self) -> list[dict[str, Any]]:
        return self._schemas

    def resolve(self, name: str) -> ToolDescriptor | None:
        if name in self._descriptors:
            return self._descriptors[name]

        by_exported = self._by_exported_name.get(name)
        if by_exported:
            return by_exported[0]

        by_alias = self._by_alias.get(name)
        if by_alias:
            return by_alias[0]

        by_name = self._by_name.get(name)
        if by_name:
            return by_name[0]

        return None

    @property
    def modules(self) -> dict[str, list[ToolDescriptor]]:
        return self._by_alias

    def has_module(self, alias: str) -> bool:
        return alias in self._by_alias

    def find_alias(self, alias: str) -> list[ToolDescriptor]:
        return self._by_alias.get(alias, [])

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> Any:
        return await self._source_of(descriptor).invoke(descriptor, kwargs, ctx=ctx)

    async def call(self, tool_call: ToolCall, ctx: BeforeToolCallCtx | None = None) -> ToolCallResult:
        descriptor = self.resolve(tool_call.tool_name)
        if descriptor is None:
            return ToolCallResult(
                tool_call_id=tool_call.tool_call_id,
                content=f"Tool not found: {tool_call.tool_name!r}",
            )

        try:
            tool_source: ToolSource = self._source_of(descriptor)
            result = await tool_source.invoke(descriptor, tool_call.tool_args, ctx=ctx)
        except Exception as exc:
            return ToolCallResult(
                tool_call_id=tool_call.tool_call_id,
                content=f"Error executing tool {tool_call.tool_name!r}: {exc}",
            )

        return ToolCallResult(
            tool_call_id=tool_call.tool_call_id,
            content=result,
        )

    def _rebuild(self) -> None:
        by_alias: dict[str, list[ToolDescriptor]] = {}
        by_name: dict[str, list[ToolDescriptor]] = {}
        by_exported: dict[str, list[ToolDescriptor]] = {}
        for descriptor in self.descriptors:
            by_alias.setdefault(descriptor.alias, []).append(descriptor)
            if descriptor.namespace != descriptor.alias:
                by_alias.setdefault(descriptor.namespace, []).append(descriptor)
            by_name.setdefault(descriptor.name, []).append(descriptor)
            by_exported.setdefault(descriptor.exported_name, []).append(descriptor)
        self._by_alias = by_alias
        self._by_name = by_name
        self._by_exported_name = by_exported
        self._schemas = []
        for descriptor in self.descriptors:
            schema = dict(descriptor.schema)
            schema["name"] = descriptor.exported_name
            self._schemas.append(schema)

    @property
    def tool_tree(self) -> dict[str, Any]:
        tree: dict[str, Any] = {}
        for alias, descriptors in self._by_alias.items():
            parts = alias.split(".")
            node = tree
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            leaf = parts[-1]
            node.setdefault(leaf, {})
            node[leaf].setdefault("__tools__", [])
            for d in descriptors:
                if any(existing["id"] == d.id for existing in node[leaf]["__tools__"]):
                    continue
                node[leaf]["__tools__"].append({
                    "id": d.id,
                    "name": d.name,
                    "doc": d.doc,
                    "schema": d.schema,
                    "meta": d.metadata,
                })
        return tree
