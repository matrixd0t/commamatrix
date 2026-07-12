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
    TOOL_MODULES,
    AsyncOrSyncFunction,
    ToolDescriptor,
    ToolSource,
)
from .extension_source import PythonExtensionSource

_INJECTABLE_TYPES: set[type] = {BeforeToolCallCtx}


class PythonToolSource(PythonExtensionSource[ToolDescriptor], ToolSource):
    """
    Python-backed tool source.

    Discovers ``@tool``-decorated functions via module scanning and
    executes them with type-based injection of ``BeforeToolCallCtx``.

    If a tool function declares a parameter annotated with
    ``BeforeToolCallCtx``, that parameter is:
        - **injected** at call time with the current runtime context,
        - **excluded** from the JSON Schema sent to the LLM.
    """

    def __init__(self) -> None:
        super().__init__()
        self._functions: dict[str, AsyncOrSyncFunction] = {}

    def scan(self) -> list[ToolDescriptor]:
        self._functions.clear()
        return cast(list[ToolDescriptor], list(super().scan()))

    @property
    def extension_modules(self) -> set[str]:
        return TOOL_MODULES

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

        return ToolDescriptor(
            id=descriptor_id,
            namespace=namespace,
            alias=alias,
            name=object_name,
            doc=self._build_doc(fn, alias=alias_for_doc),
            schema=build_json_schema(_schema_fn(fn)),
            metadata=metadata,
            _source_ref=weakref.ref(self),
        )

    async def invoke(self, descriptor: ToolDescriptor, kwargs: dict[str, Any], ctx: BeforeToolCallCtx | None = None) -> object:
        """
        Execute the tool function with type-based injection.

        Parameters annotated with ``BeforeToolCallCtx`` are injected from
        *ctx* and excluded from *kwargs* before calling the function.
        If *ctx* is ``None``, injectable parameters are left at their
        defaults (or the call fails if they have none).
        """
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
    """Return True if *annotation* is an injectable type (e.g. ``BeforeToolCallCtx``)."""
    return annotation in _INJECTABLE_TYPES


def _injectable_params(fn: AsyncOrSyncFunction) -> dict[str, type]:
    """Return ``{param_name: type}`` for parameters with injectable annotations."""
    hints = _type_hints(fn)
    return {
        name: hints[name]
        for name, param in inspect.signature(fn).parameters.items()
        if name in hints and _is_injectable(hints[name])
    }


def _inject(fn: AsyncOrSyncFunction, kwargs: dict[str, Any], ctx: BeforeToolCallCtx) -> dict[str, Any]:
    """Return a copy of kwargs with injectable parameters filled from ctx."""
    result = dict(kwargs)
    for name, annotation in _injectable_params(fn).items():
        if annotation is BeforeToolCallCtx:
            result[name] = ctx
    return result


def _schema_fn(fn: AsyncOrSyncFunction):
    """
    Create a thin wrapper around fn with injectable parameters removed.

    ``build_json_schema`` inspects ``inspect.signature()`` — this wrapper
    ensures ``BeforeToolCallCtx`` parameters are invisible to the schema generator.
    """
    sig = inspect.signature(fn)
    skip = set(_injectable_params(fn))
    params = [p for name, p in sig.parameters.items() if name not in skip]
    wrapper = functools.wraps(fn)(lambda *a, **kw: None)
    wrapper.__signature__ = sig.replace(parameters=params)
    return wrapper


def _signature_metadata(fn: AsyncOrSyncFunction) -> list[dict[str, Any]]:
    hints = _type_hints(fn)
    result: list[dict[str, Any]] = []
    for name, parameter in inspect.signature(fn).parameters.items():
        if name in _injectable_params(fn):
            continue
        item = {
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
    """Resolve postponed annotations for injection and schema generation."""
    try:
        return {k: v for k, v in get_type_hints(fn).items() if k != "return"}
    except Exception:
        return dict(getattr(fn, "__annotations__", {}))
