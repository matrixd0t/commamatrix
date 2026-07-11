# builtin/codeact/virtual_imports.py

from __future__ import annotations

import sys
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any, Callable, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from ...api.hooks import BeforeToolCallCtx, RunCtx
    from ...api.storage import Storage
    from ...api.tool import ToolDescriptor


class VirtualImportRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], ModuleType]] = {}

    def register(self, name: str, factory: Callable[[], ModuleType]) -> None:
        self._factories[name] = factory

    def unregister(self, name: str) -> None:
        self._factories.pop(name, None)

    def clear(self) -> None:
        self._factories.clear()

    def has_module(self, name: str) -> bool:
        return name in self._factories

    def get_module(self, name: str) -> ModuleType | None:
        factory = self._factories.get(name)
        if factory is None:
            return None
        return factory()

    @property
    def module_names(self) -> list[str]:
        return list(self._factories.keys())


class _VirtualModuleFinder(MetaPathFinder):
    def __init__(self, registry: VirtualImportRegistry) -> None:
        self._registry = registry

    def find_spec(self, fullname: str, path=None, target=None) -> ModuleSpec | None:
        if "." in fullname:
            return None
        if not self._registry.has_module(fullname):
            return None
        return ModuleSpec(fullname, _VirtualModuleLoader(self._registry))


class _VirtualModuleLoader:
    def __init__(self, registry: VirtualImportRegistry) -> None:
        self._registry = registry

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        module = self._registry.get_module(spec.name)
        if module is not None:
            return module
        return ModuleType(spec.name)

    def exec_module(self, module: ModuleType) -> None:
        pass


_finder: _VirtualModuleFinder | None = None


def install_import_hook(registry: VirtualImportRegistry) -> None:
    global _finder
    if _finder is not None:
        return
    _finder = _VirtualModuleFinder(registry)
    sys.meta_path.insert(0, _finder)


def uninstall_import_hook() -> None:
    global _finder
    if _finder is None:
        return
    sys.meta_path.remove(_finder)
    _finder = None


class _LazyProxy:
    __slots__ = ("_resolver",)

    def __init__(self, resolver: Callable[[], Any]) -> None:
        object.__setattr__(self, "_resolver", resolver)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def resolve():
            obj = self._resolver()
            if obj is None:
                raise AttributeError(f"Cannot access '{name}' on None")
            return getattr(obj, name)

        return _LazyProxy(resolve)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        val = self._resolver()
        if callable(val):
            return val(*args, **kwargs)
        raise TypeError(f"{val!r} is not callable")

    def __await__(self):
        val = self._resolver()
        if hasattr(val, "__await__"):
            return val.__await__()
        return _yield_value(val)

    def __repr__(self) -> str:
        return f"<LazyProxy>"


def _yield_value(val: Any):
    yield val


class _ToolsAccessor:
    __slots__ = ("_provider",)

    def __init__(self, provider: ContextProvider) -> None:
        object.__setattr__(self, "_provider", provider)

    async def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> Any:
        return await self._provider.invoke_tool(tool_name, args or {})

    async def search(self, query: str, limit: int = 5) -> Any:
        return await self._provider.search_tools(query, limit)

    def __repr__(self) -> str:
        return "<ToolsAccessor>"


@runtime_checkable
class ContextProvider(Protocol):
    @property
    def run(self) -> RunCtx: ...
    @property
    def tool_call(self) -> ToolCall: ...
    @property
    def storage(self) -> Storage: ...
    async def invoke_tool(self, tool_name: str, args: dict[str, Any]) -> Any: ...
    async def search_tools(self, query: str, limit: int) -> list[Any]: ...


def register_context(registry: VirtualImportRegistry, provider: ContextProvider) -> None:
    registry.register("context", lambda: _make_context_module(provider))


def register_tool_alias(registry: VirtualImportRegistry, alias: str, descriptors: list[ToolDescriptor], invoker: Callable[[str, dict[str, Any]], Any]) -> None:
    registry.register(alias, lambda a=alias, ds=descriptors, inv=invoker: _make_tool_module(a, ds, inv))


def _make_context_module(provider: ContextProvider) -> ModuleType:
    module = ModuleType("context")
    module.run = _LazyProxy(lambda: provider.run)  # type: ignore[attr-defined]
    module.tool_call = _LazyProxy(lambda: provider.tool_call)  # type: ignore[attr-defined]
    module.storage = _LazyProxy(lambda: provider.storage)  # type: ignore[attr-defined]
    module.tools = _ToolsAccessor(provider)  # type: ignore[attr-defined]
    module.__all__ = ["run", "tool_call", "storage", "tools"]  # type: ignore[attr-defined]
    return module


def _make_tool_module(alias: str, descriptors: list[ToolDescriptor], invoker: Callable[[str, dict[str, Any]], Any]) -> ModuleType:
    module = ModuleType(alias)
    names: list[str] = []
    for d in descriptors:
        name = d.name

        def make_proxy(n: str) -> _LazyProxy:
            return _LazyProxy(lambda: lambda **kw: invoker(n, kw))

        setattr(module, name, make_proxy(name))
        names.append(name)
    module.__all__ = names  # type: ignore[attr-defined]
    return module


class DirectContextProvider:
    __slots__ = ("_ctx",)

    def __init__(self, ctx: BeforeToolCallCtx) -> None:
        object.__setattr__(self, "_ctx", ctx)

    @property
    def run(self) -> RunCtx:
        return self._ctx.run

    @property
    def tool_call(self) -> ToolCall:
        return self._ctx.tool_call

    @property
    def storage(self) -> Storage:
        return self._ctx.run.agent.storage

    async def invoke_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        from .runtime import CodeActRuntime
        runtime = self._ctx.run.agent.services.require(CodeActRuntime)
        return await runtime.invoke_tool(self._ctx, tool_name, args)

    async def search_tools(self, query: str, limit: int) -> list[Any]:
        from .runtime import CodeActRuntime
        runtime = self._ctx.run.agent.services.get(CodeActRuntime)
        if runtime is None:
            return []
        return runtime.searcher.search(query, limit=limit)
