# components/tool.py

from __future__ import annotations

import functools
import inspect
import weakref

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, cast, get_type_hints, overload

from matrix_fn_schema import build_json_schema

from ..core.classes.descriptor import Descriptor
from ..core.classes.source import Source
from ..core.classes.manager import Manager
from ..core.classes.source import PythonSource
from .llm_adapter import ToolCall, ToolCallResult
from .hook import BeforeToolCallCtx


DEFAULT_TOOL_SEARCH_AMOUNT = 5
TOOL_ATTRIBUTE = "__commamatrix_tool__"

type AsyncOrSyncFunction = Callable[..., object] | Callable[..., Awaitable[object]]
type Decorator[F: AsyncOrSyncFunction] = Callable[[F], F]


class AmbiguousToolError(RuntimeError):
    def __init__(self, name: str, candidates: list[ToolDescriptor]) -> None:
        lines = [f"Tool name {name!r} is ambiguous. Candidates:"]
        for d in candidates:
            lines.append(f"  - {d.id} from {d.namespace} (alias={d.alias})")
        lines.append("Use distinct aliases or tool names.")
        super().__init__("\n".join(lines))
        self.name = name
        self.candidates = candidates


@dataclass(frozen=True, slots=True)
class ToolDescriptor(Descriptor):
    """
    Describes a registered tool: namespace, alias, name, JSON Schema, and docstring.
    The public name visible to LLM is computed by ToolManager.public_name().
    Used by ToolManager for resolution.
    """
    namespace: str
    alias: str
    name: str
    doc: str
    schema: dict[str, Any]
    meta: dict[str, Any]

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "alias": self.alias,
            "name": self.name,
            "doc": self.doc,
            "schema": self.schema,
            "meta": self.meta,
        }


class ToolSource(Source[ToolDescriptor]):
    """
    Source ABC for tool execution.

    The invoke() method bridges a descriptor back to the actual callable.
    Synchronous tools are called directly on the event loop — CodeAct
    does **not** offload them to a thread pool.  Long-running or blocking
    tools must be written as ``async def`` functions so they yield
    control back to the event loop at await points.
    """

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> object:
        raise NotImplementedError


@overload
def tool(fn: AsyncOrSyncFunction) -> AsyncOrSyncFunction: ...
@overload
def tool(**metadata: Any) -> Decorator: ...


def tool(arg: AsyncOrSyncFunction | None = None, **meta: Any):
    """Decorator marking a function as a discoverable tool.
    Stamps TOOL_ATTRIBUTE with optional meta. Use bare (@tool)
    or with keyword arguments for extra meta."""
    def decorate(fn: AsyncOrSyncFunction, metadata: dict[str, Any]):
        setattr(fn, TOOL_ATTRIBUTE, metadata)
        return fn

    if arg is not None:
        return decorate(arg, {})

    return lambda fn: decorate(fn, meta)


class PythonToolSource(PythonSource[ToolDescriptor], ToolSource):
    """Scans @tool-decorated functions in scope modules, builds
    ToolDescriptors with JSON Schema, and provides invoke() to
    call the original function (with optional ctx injection).

    Synchronous tools are invoked directly on the event loop without
    ``to_thread`` or equivalent offloading.  Tools that perform
    long-running or blocking work must be declared as ``async def``
    so they can yield control at await points.  CodeAct does not
    and will not inject thread-pool execution for synchronous tool
    functions — that is the tool author's responsibility."""

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
        alias = metadata.get('alias')
        if alias is None:
            alias = namespace.rsplit('.', 1)[-1]
        if alias and not alias.isidentifier():
            raise ValueError(f"Alias {alias!r} is not a valid Python identifier in tool {fn.__name__!r}")
        alias_for_doc: str | None = metadata.get('alias')

        descriptor = ToolDescriptor(
            id=descriptor_id,
            namespace=namespace,
            alias=alias,
            name=object_name,
            doc=self._build_doc(fn, alias=alias_for_doc),
            schema=build_json_schema(_schema_fn(fn)),
            meta=metadata,
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


_INJECTABLE_TYPES = {BeforeToolCallCtx}


def _is_injectable(annotation: Any) -> bool:
    return annotation in _INJECTABLE_TYPES


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
    """Central tool registry. Maintains alias/name/public_name/id index
    maps for multi-step resolution. The call() method executes a
    ToolCall by resolving the tool name and invoking it through its source."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._python_source = PythonToolSource()
        self.mount(self._python_source)
        self._by_alias: dict[str, list[ToolDescriptor]] = {}
        self._by_name: dict[str, list[ToolDescriptor]] = {}
        self._by_public_name: dict[str, list[ToolDescriptor]] = {}
        self._by_id: dict[str, ToolDescriptor] = {}
        self._schemas: list[dict[str, Any]] = []

    def public_name(self, descriptor: ToolDescriptor) -> str:
        if not descriptor.alias:
            return descriptor.name
        return f"{descriptor.alias}_{descriptor.name}"

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    @property
    def fingerprint(self) -> str | None:
        return self._fingerprint

    def schemas(self) -> list[dict[str, Any]]:
        return self._schemas

    def resolve(self, name: str) -> ToolDescriptor | None:
        candidates = self._by_public_name.get(name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        raise AmbiguousToolError(name, candidates)

    def resolve_id(self, id_str: str) -> ToolDescriptor | None:
        return self._by_id.get(id_str)

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
        by_public: dict[str, list[ToolDescriptor]] = {}
        by_id: dict[str, ToolDescriptor] = {}
        for descriptor in self.descriptors:
            by_name.setdefault(descriptor.name, []).append(descriptor)
            by_id[descriptor.id] = descriptor
            public = self.public_name(descriptor)
            by_public.setdefault(public, []).append(descriptor)
            if descriptor.alias:
                by_alias.setdefault(descriptor.alias, []).append(descriptor)
        self._by_alias = by_alias
        self._by_name = by_name
        self._by_public_name = by_public
        self._by_id = by_id
        self._schemas = []
        for descriptor in self.descriptors:
            schema = dict(descriptor.schema)
            schema["name"] = self.public_name(descriptor)
            self._schemas.append(schema)

    @property
    def tool_tree(self) -> dict[str, Any]:
        return self.build_tool_tree(self.descriptors)

    @staticmethod
    def build_tool_tree(descriptors: Iterable[ToolDescriptor]) -> dict[str, Any]:
        tree: dict[str, Any] = {"tools": {}}
        for d in descriptors:
            if not d.alias:
                continue
            node = tree["tools"].setdefault(d.alias, {})
            node.setdefault("__tools__", [])
            if any(existing["id"] == d.id for existing in node["__tools__"]):
                continue
            node["__tools__"].append({
                "id": d.id,
                "name": d.name,
                "doc": d.doc,
                "schema": d.schema,
                "meta": d.meta,
            })
        return tree
