# builtin/planner/service.py

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TYPE_CHECKING, cast

from matrix_planner import Planner, Task as PlannerTask

from ...core.classes.descriptor import Descriptor
from ...core.classes.manager import Manager
from ...core.classes.source import PythonSource
from ...utils import await_if_needed
from .decorators import TASK_ATTRIBUTE

if TYPE_CHECKING:
    from ...core.agent.agent import Agent


@dataclass(frozen=True, slots=True)
class ScheduledTaskDescriptor(Descriptor):
    """Metadata for a function-backed scheduled task."""

    module: str
    name: str
    schedule_fingerprint: str
    options_fingerprint: dict[str, str] = field(default_factory=dict)

    @property
    def task_id(self) -> str:
        return self.id

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "module": self.module,
            "name": self.name,
            "schedule": self.schedule_fingerprint,
            "options": self.options_fingerprint,
        }


@dataclass(slots=True, kw_only=True)
class ScheduledTaskContext:
    """Runtime context passed to a scheduled task when it declares ``ctx``."""

    agent: Agent
    task_id: str
    scheduled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


ScheduledTaskHandler = Callable[..., Any]


def _stable_value(value: Any) -> str:
    if callable(value):
        return f"{getattr(value, '__module__', '')}:{getattr(value, '__qualname__', repr(value))}"
    return repr(value)


def _schedule_fingerprint(schedule: Any) -> str:
    parts: list[str] = [
        f"{type(schedule).__module__}.{type(schedule).__qualname__}"
    ]
    if dataclasses.is_dataclass(schedule):
        for item in dataclasses.fields(schedule):
            if item.name.startswith("_"):
                continue
            parts.append(f"{item.name}={_stable_value(getattr(schedule, item.name))}")
    else:
        parts.append(repr(schedule))
    return "|".join(parts)


class PythonScheduledTaskSource(PythonSource[ScheduledTaskDescriptor]):
    """Discover ``@task`` functions and retain their live callables."""

    def __init__(self) -> None:
        super().__init__()
        self._functions: dict[str, ScheduledTaskHandler] = {}
        self._options: dict[str, dict[str, Any]] = {}

    @property
    def marker_attribute(self) -> str:
        return TASK_ATTRIBUTE

    def scan(self) -> list[ScheduledTaskDescriptor]:
        previous_functions = self._functions
        previous_options = self._options
        self._functions = {}
        self._options = {}
        try:
            return super().scan()
        except BaseException:
            self._functions = previous_functions
            self._options = previous_options
            raise

    def build_descriptor(self,  object_name: str, obj: object) -> ScheduledTaskDescriptor | None:
        fn = cast(ScheduledTaskHandler, obj)
        raw_params: Any = getattr(fn, TASK_ATTRIBUTE)
        params = cast(dict[str, Any], dict(raw_params))
        module = getattr(fn, "__module__", "") or ""
        function_name = getattr(fn, "__name__", object_name)
        task_id = f"{module}:{function_name}"
        self._functions[task_id] = fn
        self._options[task_id] = params

        fingerprint_fields = {
            "name": _stable_value(params.get("name")),
            "args": _stable_value(params.get("args", ())),
            "kwargs": _stable_value(params.get("kwargs", {})),
            "max_retries": _stable_value(params.get("max_retries", 0)),
            "backoff": _stable_value(params.get("backoff", 0.0)),
            "on_error": _stable_value(params.get("on_error")),
            "timeout": _stable_value(params.get("timeout")),
        }
        return ScheduledTaskDescriptor(
            id=task_id,
            module=module,
            name=function_name,
            schedule_fingerprint=_schedule_fingerprint(params["schedule"]),
            options_fingerprint=fingerprint_fields,
            _source_ref=weakref.ref(self),
        )

    def _handler(self, descriptor: ScheduledTaskDescriptor) -> ScheduledTaskHandler:
        fn = self._functions.get(descriptor.id)
        if fn is None:
            raise RuntimeError(f"Scheduled task {descriptor.id} is not owned by this source")
        return fn

    async def invoke(self, descriptor: ScheduledTaskDescriptor, agent: Agent) -> Any:
        fn = self._handler(descriptor)
        params = self._options[descriptor.id]
        args = tuple(params.get("args", ()))
        kwargs = dict(params.get("kwargs", {}))
        signature = inspect.signature(fn)
        if "ctx" in signature.parameters and "ctx" not in kwargs:
            kwargs["ctx"] = ScheduledTaskContext(
                agent=agent,
                task_id=descriptor.task_id,
            )
        if inspect.iscoroutinefunction(fn):
            result = fn(*args, **kwargs)
        else:
            result = await asyncio.to_thread(lambda: fn(*args, **kwargs))
        return await await_if_needed(result)

    def make_planner_task(self, descriptor: ScheduledTaskDescriptor, agent: Agent) -> PlannerTask:
        params = self._options[descriptor.id]

        async def _invoke() -> Any:
            return await self.invoke(descriptor, agent)

        async def on_error(error: Exception) -> None:
            raw_handler: Any = self._options.get(descriptor.id, {}).get("on_error")
            if raw_handler is None:
                return
            handler = cast(Callable[[Exception], Any], raw_handler)
            await await_if_needed(handler(error))

        return PlannerTask(
            task_id=descriptor.task_id,
            func=_invoke,
            schedule=params["schedule"],
            name=params.get("name") or descriptor.name,
            max_retries=params.get("max_retries", 0),
            backoff=params.get("backoff", 0.0),
            on_error=on_error if params.get("on_error") is not None else None,
            timeout=params.get("timeout"),
        )


class AgentScheduler(Manager[ScheduledTaskDescriptor]):
    """Owns one Planner and reconciles it with active extension tasks."""

    def __init__(self, agent: Agent, **kwargs: Any) -> None:
        super().__init__(agent, **kwargs)
        self._python_source = PythonScheduledTaskSource()
        self.mount(self._python_source)
        self._planner = Planner()
        self._registered: dict[str, str] = {}

    @property
    def planner(self) -> Planner:
        return self._planner

    def set_scope(self, scope: list[str]) -> None:
        self._python_source.set_scope(scope)

    async def start(self) -> None:
        await super().start()
        await self._planner.start()

    async def refresh(self) -> None:
        await super().refresh()
        await self._reconcile()

    async def stop(self) -> None:
        await self._planner.stop()
        for task_id in tuple(self._registered):
            await self._planner.remove(task_id)
        self._registered.clear()
        await super().stop()

    async def _reconcile(self) -> None:
        desired = {descriptor.id: descriptor for descriptor in self.descriptors}

        for task_id, fingerprint in tuple(self._registered.items()):
            descriptor = desired.get(task_id)
            if descriptor is None or descriptor.fingerprint != fingerprint:
                await self._planner.remove(task_id)
                del self._registered[task_id]

        for descriptor in desired.values():
            if descriptor.id in self._registered:
                continue
            source = cast(PythonScheduledTaskSource, self._source_of(descriptor))
            self._planner.add(source.make_planner_task(descriptor, self.agent))
            self._registered[descriptor.id] = descriptor.fingerprint


__all__ = [
    "AgentScheduler",
    "PythonScheduledTaskSource",
    "ScheduledTaskContext",
    "ScheduledTaskDescriptor",
]
