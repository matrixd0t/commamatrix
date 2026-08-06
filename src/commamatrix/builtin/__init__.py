# builtin/__init__.py

"""Optional built-in plugins loaded explicitly by importing their modules."""

from importlib import import_module
from types import ModuleType


_MODULES = {
    "apply_patch": "apply_patch",
    "codeact": "codeact",
    "data_tools": "data_tools",
    "filesystem": "filesystem",
    "http_connector": "http_connector",
    "instructions": "instructions",
    "llm_http_adapter": "llm_http_adapter",
    "mcp": "mcp",
    "multi_dialog": "multi_dialog",
    "multi_user": "multi_user",
    "planner": "planner",
    "self_extension": "self_extension",
    "simple_fs": "simple_fs",
    "sql": "sql",
    "storage_utils": "storage_utils",
    "subagent": "subagent",
    "web_utils": "web_utils",
}

__all__ = list(_MODULES)


def __getattr__(name: str) -> ModuleType:
    module_name = _MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
