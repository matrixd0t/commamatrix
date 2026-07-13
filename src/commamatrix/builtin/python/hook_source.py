# builtin/python/hook_source.py

from __future__ import annotations

import inspect
import weakref
from typing import Any, cast

from ...api.hooks import HOOK_ATTRIBUTE, HookDescriptor, HookSource
from .extension_source import PythonExtensionSource


class PythonHookSource(PythonExtensionSource[HookDescriptor], HookSource):
    """Python-backed hook source.

    Discovers @hook-decorated functions via module scanning and
    stores their handlers for execution.
    """

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, Any] = {}

    def scan(self) -> list[HookDescriptor]:
        self._handlers.clear()
        return super().scan()

    @property
    def marker_attribute(self) -> str:
        return HOOK_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> HookDescriptor | None:
        params = getattr(obj, HOOK_ATTRIBUTE)
        descriptor_id = f"hook://{obj.__module__}/{object_name}"
        self._handlers[descriptor_id] = cast(Any, obj)
        return HookDescriptor(
            id=descriptor_id,
            event=params["event"],
            priority=params.get("priority", 0),
            metadata={},
            _source_ref=weakref.ref(self),
        )

    async def invoke(self, descriptor: HookDescriptor, ctx: object) -> object:
        handler = self._handlers.get(descriptor.id)
        if handler is None:
            raise RuntimeError(f"Hook {descriptor.id} is not owned by this source")
        result = handler(ctx)
        if inspect.isawaitable(result):
            return await result
        return result
