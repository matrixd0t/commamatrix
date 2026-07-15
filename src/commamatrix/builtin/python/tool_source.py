# builtin/python/tool_source.py

from __future__ import annotations

import functools
import inspect
import weakref
from typing import Any, cast, get_type_hints

from matrix_fn_schema import build_json_schema

from ...api.hooks import BeforeToolCallCtx
from ...api.tool import (
    TOOL_ATTRIBUTE,
    AsyncOrSyncFunction,
    ToolDescriptor,
    ToolSource,
)
from .base_source import PythonSource

_INJECTABLE_TYPES: set[type] = {BeforeToolCallCtx}


class PythonToolSource(PythonSource[ToolDescriptor], ToolSource):
    """Python-backed tool source.

    Discovers @tool-decorated functions via module scanning and
    executes them with type-based injection of BeforeToolCallCtx.

    If a tool function declares a parameter annotated with
    BeforeToolCallCtx, that parameter is injected at call time
    with the current runtime context and excluded from the JSON
    Schema sent to the LLM.
    """

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
        if param_type is BeforeToolCallCtx:
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
