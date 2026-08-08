# builtin/planner/decorators.py

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from matrix_planner import Schedule

TASK_ATTRIBUTE = "__commamatrix_scheduled_task__"
TaskFunction = TypeVar("TaskFunction", bound=Callable[..., Any])


def task(schedule: Schedule | None = None, **options: Any):
    """Mark a plugin function as an in-memory scheduled task.

    The schedule is intentionally kept in the extension source. The task is
    recreated when the extension is loaded, so its identity is derived from
    the defining module and function name rather than generated at runtime.
    """
    if schedule is None or not isinstance(schedule, Schedule):
        raise TypeError("@task requires a matrix_planner Schedule")

    allowed = {
        "name",
        "args",
        "kwargs",
        "max_retries",
        "backoff",
        "on_error",
        "timeout",
    }
    unknown = set(options) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise TypeError(f"Unsupported scheduled task option(s): {names}")

    metadata = {
        "schedule": schedule,
        "name": options.get("name"),
        "args": tuple(options.get("args", ())),
        "kwargs": dict(options.get("kwargs", {})),
        "max_retries": options.get("max_retries", 0),
        "backoff": options.get("backoff", 0.0),
        "on_error": options.get("on_error"),
        "timeout": options.get("timeout"),
    }

    def decorate(fn: TaskFunction) -> TaskFunction:
        setattr(fn, TASK_ATTRIBUTE, metadata)
        return fn

    return decorate


__all__ = ["TASK_ATTRIBUTE", "task"]
