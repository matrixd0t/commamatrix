# builtin/python/hook_source.py

from __future__ import annotations

import inspect
import sys
import weakref

from ...api.hooks import (
    HOOK_ATTRIBUTE,
    HOOK_HANDLER_METADATA_KEY,
    KNOWN_HOOK_MODULES,
    HookDescriptor,
    HookSource,
)


class PythonHookSource(HookSource):
    """
    Hook source that discovers functions decorated with ``@before_run``,
    ``@after_llm_call``, etc.

    Scans all modules listed in ``KNOWN_HOOK_MODULES`` at scan time
    and builds ``HookDescriptor`` instances.  The Python callable is
    stored in ``metadata[HOOK_HANDLER_METADATA_KEY]`` and is invoked
    by the base ``HookSource.invoke()``.
    """

    def scan(self) -> list[HookDescriptor]:
        descriptors: list[HookDescriptor] = []

        for module_name in sorted(KNOWN_HOOK_MODULES):
            module = sys.modules.get(module_name)
            if module is None:
                continue

            for name, fn in inspect.getmembers(module, inspect.isfunction):
                params = getattr(fn, HOOK_ATTRIBUTE, None)
                if params is None:
                    continue

                descriptors.append(
                    HookDescriptor(
                        id=f'hook://{module_name}/{name}',
                        _source_ref=weakref.ref(self),
                        event=params['event'],
                        priority=params.get('priority', 0),
                        metadata={HOOK_HANDLER_METADATA_KEY: fn},
                    )
                )

        return descriptors
