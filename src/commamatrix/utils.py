# core/utils.py

from __future__ import annotations

import inspect
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any


def framework_prefix() -> str:
    """Return the import prefix used by the framework package."""
    parts = __name__.split(".")
    return ".".join(parts[: parts.index("commamatrix") + 1])


FP = framework_prefix()


async def await_if_needed(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


def to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(value) for value in obj]
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump(mode="json"))
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: to_jsonable(getattr(obj, field.name))
            for field in fields(obj)
        }
    if hasattr(obj, "__dict__"):
        return {
            key: to_jsonable(value)
            for key, value in obj.__dict__.items()
            if not key.startswith("_")
        }
    return str(obj)
