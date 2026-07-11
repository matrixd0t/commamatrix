# builtin/codeact/docs/python.py

from __future__ import annotations

import inspect

from ....api.tool import AsyncOrSyncFunction, ToolDescriptor
from . import ToolDocBuilder


class PythonToolDocBuilder(ToolDocBuilder):
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def build(self, descriptor: ToolDescriptor) -> str:
        if descriptor.id in self._cache:
            return self._cache[descriptor.id]
        doc = descriptor.doc
        self._cache[descriptor.id] = doc
        return doc

    def build_from_fn(self, fn: AsyncOrSyncFunction, alias: str | None = None) -> str:
        parts: list[str] = []

        if alias is not None:
            parts.append(f'[ alias: {alias} ]')

        prefix = 'async ' if inspect.iscoroutinefunction(fn) else ''
        parts.append(f'{prefix}def {fn.__name__}{inspect.signature(fn)}:')
        parts.append('"""')
        parts.append(inspect.getdoc(fn) or '')
        parts.append('"""')

        return '\n'.join(parts)
