# builtin/sql/__init__.py

from importlib import import_module
from types import ModuleType


_MODULES = {
    "postgres_storage": "postgres_storage",
    "sqlite_storage": "sqlite_storage",
    "sql_storage": "sql_storage",
}

__all__ = list(_MODULES)


def __getattr__(name: str) -> ModuleType:
    module_name = _MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    globals()[name] = module
    return module
