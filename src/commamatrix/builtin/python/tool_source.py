# builtin/python/tool_source.py

from __future__ import annotations

import inspect
import sys
import weakref
from typing import Any

from matrix_fn_schema import build_json_schema

from ...api.tool import (
    TOOL_ATTRIBUTE,
    KNOWN_TOOL_MODULES,
    ToolDescriptor,
    ToolSource,
    AsyncOrSyncFunction,
)


def build_tool_doc(
    fn: AsyncOrSyncFunction,
    alias: str | None = None,
) -> str:
    """
    Build a human-readable documentation string for a tool function.

    The result is used by BM25 search to match natural-language queries
    against tool descriptions.  Includes the alias (if set), signature,
    and docstring.
    """

    parts: list[str] = []

    if alias is not None:
        parts.append(f"[ alias: {alias} ]")

    prefix = "async " if inspect.iscoroutinefunction(fn) else ""

    parts.append(
        f"{prefix}def {fn.__name__}{inspect.signature(fn)}:"
    )

    parts.append('"""')
    parts.append(inspect.getdoc(fn) or "")
    parts.append('"""')

    return "\n".join(parts)


class PythonToolSource(ToolSource):
    """
    Tool source that discovers functions decorated with ``@tool``.

    Scans all modules listed in ``KNOWN_TOOL_MODULES`` at scan time,
    builds ``ToolDescriptor`` instances with JSON Schemas generated
    via ``matrix_fn_schema``, and executes tools by calling the
    stored Python callable (sync or async).
    """

    def scan(self) -> list[ToolDescriptor]:
        descriptors: list[ToolDescriptor] = []

        for module_name in sorted(KNOWN_TOOL_MODULES):
            module = sys.modules.get(module_name)
            if module is None:
                continue

            for _, fn in inspect.getmembers(module, inspect.isfunction):
                metadata = getattr(fn, TOOL_ATTRIBUTE, None)
                if metadata is None:
                    continue

                metadata = dict(metadata)
                metadata["fn"] = fn

                namespace = fn.__module__
                alias = metadata.get("alias", namespace)
                name = fn.__name__

                descriptors.append(
                    ToolDescriptor(
                        id=f"python://{namespace}/{name}",
                        namespace=namespace,
                        alias=alias,
                        name=name,
                        doc=build_tool_doc(fn, alias=metadata.get("alias")),
                        schema=build_json_schema(fn),
                        metadata=metadata,
                        _source_ref=weakref.ref(self),
                    )
                )

        return descriptors

    async def invoke(
        self,
        descriptor: ToolDescriptor,
        kwargs: dict[str, Any],
    ) -> object:
        fn = descriptor.metadata["fn"]

        if inspect.iscoroutinefunction(fn):
            return await fn(**kwargs)

        return fn(**kwargs)
