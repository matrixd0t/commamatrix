# core/virtual_imports.py

from __future__ import annotations

import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import TYPE_CHECKING, Any

from ..api.tool import ToolDescriptor

if TYPE_CHECKING:
    from .tool_runtime import ToolRuntime


class ToolModuleFinder(MetaPathFinder):
    def __init__(self, runtime: ToolRuntime) -> None:
        self._runtime = runtime

    def find_spec(self, fullname: str, path=None, target=None) -> ModuleSpec | None:
        if "." in fullname:
            return None
        if not self._runtime.has_module(fullname):
            return None
        return ModuleSpec(fullname, ToolModuleLoader(self._runtime))


class ToolModuleLoader(Loader):
    def __init__(self, runtime: ToolRuntime) -> None:
        self._runtime = runtime

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        return ModuleType(spec.name)

    def exec_module(self, module: ModuleType) -> None:
        alias = module.__name__
        descriptors = self._runtime.find_alias(alias)
        names: list[str] = []
        for d in descriptors:
            fn = _make_proxy(self._runtime, d)
            setattr(module, d.name, fn)
            names.append(d.name)
        setattr(module, "__all__", names)


def _make_proxy(runtime, descriptor: ToolDescriptor) -> Any:
    async def proxy(**kwargs: Any) -> Any:
        return await runtime.invoke(descriptor, **kwargs)

    proxy.__name__ = descriptor.name
    proxy.__qualname__ = descriptor.name
    proxy.__doc__ = descriptor.doc
    proxy.__module__ = descriptor.alias
    return proxy


def install_import_hook(runtime: ToolRuntime) -> ToolModuleFinder:
    for finder in sys.meta_path:
        if isinstance(finder, ToolModuleFinder):
            return finder

    finder = ToolModuleFinder(runtime)
    sys.meta_path.insert(0, finder)
    return finder
