# core/agent/lifecycle.py

"""Root lifecycle composite for Agent-owned components."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...utils import await_if_needed

from ...components.config import AgentLogger, get_agent_logger
from ..classes.lifecycle_registry import (
    LifecycleRegistration,
    is_core_component,
    lifecycle_registrations,
)
from ..classes.manager import Manager, ServiceInstanceRegistry
from ..classes.ordering import ConstraintRef, normalize_constraint_refs, resolve_order
from ..classes.service import AbstractService

if TYPE_CHECKING:
    from .agent import Agent


@dataclass(frozen=True, slots=True)
class _ChildSpec:
    key: str
    priority: int
    before: tuple[str, ...]
    after: tuple[str, ...]


class AgentLifecycle:
    """Root lifecycle composite for ordered agent-owned components.

    Core components are instantiated from registrations in ``core`` and
    ``components``. Other registrations are active only while their defining
    extension is in the agent scope.
    """

    def __init__(
        self,
        children: list[AbstractService] | None = None,
        registry: ServiceInstanceRegistry | None = None,
        *,
        agent: Agent | None = None,
        auto_register: bool = False,
    ) -> None:
        self._children: list[AbstractService] = []
        self._child_specs: dict[int, _ChildSpec] = {}
        self._children_by_key: dict[str, AbstractService] = {}
        self._registered_children: dict[str, AbstractService] = {}
        self._registered_specs: dict[str, LifecycleRegistration] = {}
        self._agent = agent
        if self._agent is None and children:
            self._agent = children[0].agent
        self._registry = registry or ServiceInstanceRegistry()
        self._refresh_lock = asyncio.Lock()
        self._started = False
        self._changed = False
        self._last_scope: tuple[str, ...] = ()

        for child in children or ():
            self.register(child)
        if auto_register:
            for registration in lifecycle_registrations():
                if is_core_component(registration):
                    self._add_registration(registration)

    @property
    def logger(self) -> AgentLogger:
        if self._agent is None:
            return get_agent_logger(self, "AgentLifecycle")
        logger = getattr(self._agent, "logger", None)
        if logger is None:
            logger = get_agent_logger(self._agent, "AgentLifecycle")
        return logger

    @property
    def registry(self) -> ServiceInstanceRegistry:
        return self._registry

    def get(self, key: str) -> AbstractService | None:
        return self._children_by_key.get(key)

    def has_key(self, key: str) -> bool:
        return key in self._children_by_key or any(registration.key == key for registration in lifecycle_registrations())

    def get_manager(self, key: str | type[AbstractService]) -> AbstractService | None:
        if isinstance(key, str):
            return self.get(key)
        for child in self._children:
            if isinstance(child, key):
                return child
        return None

    def register(
        self,
        child: AbstractService,
        *,
        key: str | None = None,
        priority: int = 0,
        before: ConstraintRef | Iterable[ConstraintRef] | None = None,
        after: ConstraintRef | Iterable[ConstraintRef] | None = None,
    ) -> None:
        """Add a component before lifecycle startup."""
        if child in self._children:
            return
        key = key or self._default_key(child)
        if key in self._children_by_key:
            raise ValueError(f"Duplicate lifecycle component key: {key!r}")
        self._children.append(child)
        self._child_specs[id(child)] = _ChildSpec(
            key=key,
            priority=priority,
            before=normalize_constraint_refs(before),
            after=normalize_constraint_refs(after),
        )
        self._children_by_key[key] = child
        self._configure_child(child)
        self._sort_children()
        child.logger.debug("Lifecycle component registered key=%s", key)

    async def add_child(
        self,
        child: AbstractService,
        *,
        key: str | None = None,
        priority: int = 0,
        before: ConstraintRef | Iterable[ConstraintRef] | None = None,
        after: ConstraintRef | Iterable[ConstraintRef] | None = None,
    ) -> None:
        if child in self._children:
            return
        self.register(child, key=key, priority=priority, before=before, after=after)
        if isinstance(child, Manager):
            child.set_scope(list(self._last_scope))
        if not self._started:
            return
        try:
            await await_if_needed(child.start())
            child.logger.info("Lifecycle component started key=%s", self._child_specs[id(child)].key)
        except BaseException:
            child.logger.exception("Lifecycle component failed to start key=%s", self._child_specs[id(child)].key)
            self._remove_child(child)
            raise

    async def remove_child(self, child: AbstractService) -> None:
        if child not in self._children:
            return
        if self._started:
            await await_if_needed(child.stop())
            child.logger.info("Lifecycle component stopped key=%s", self._child_specs[id(child)].key)
        self._remove_child(child)

    async def sync_registered(self, scope: Iterable[str]) -> None:
        """Reconcile registered components with the current extension scope."""
        scope = tuple(scope)
        active = {
            registration.key: registration
            for registration in lifecycle_registrations()
            if is_core_component(registration)
            or self._registration_is_active(registration, scope)
        }

        for key, child in tuple(self._registered_children.items()):
            registration = active.get(key)
            if registration is None or registration != self._registered_specs[key]:
                await self.remove_child(child)
                self._registered_children.pop(key, None)
                self._registered_specs.pop(key, None)

        if self._agent is None:
            if active:
                raise RuntimeError("AgentLifecycle needs an agent to instantiate registered components")
            return

        for key, registration in active.items():
            if key in self._registered_children:
                continue
            if key in self._children_by_key:
                continue
            self._add_registration(registration)

    def set_scope(self, scope: list[str]) -> None:
        scope_key = tuple(scope)
        if scope_key != self._last_scope:
            self._last_scope = scope_key
            for child in self._children:
                if isinstance(child, Manager):
                    child.set_scope(scope)
            self._mark_changed()

    async def start(self) -> None:
        if self._started:
            return
        self._sort_children()
        self.logger.info("Lifecycle startup components=%d", len(self._children))
        started_children: list[AbstractService] = []
        try:
            for child in self._children:
                started_children.append(child)
                await await_if_needed(child.start())
            self._started = True
            self._changed = False
            self.logger.info("Lifecycle startup completed")
        except BaseException:
            self.logger.exception("Lifecycle startup failed; rolling back")
            for child in reversed(started_children):
                try:
                    await await_if_needed(child.stop())
                except Exception:
                    child.logger.exception("Lifecycle rollback failed key=%s", self._child_specs[id(child)].key)
            self._registry.clear()
            raise

    async def refresh(self, force: bool = False) -> None:
        async with self._refresh_lock:
            if not force and not self._changed:
                return
            self._sort_children()
            self.logger.debug("Lifecycle refresh components=%d force=%s", len(self._children), force)
            for child in self._children:
                await await_if_needed(child.refresh())
            self._changed = False

    async def stop(self) -> None:
        self.logger.info("Lifecycle shutdown components=%d", len(self._children))
        for child in reversed(self._children):
            try:
                await await_if_needed(child.stop())
                child.logger.info("Lifecycle component stopped key=%s", self._child_specs[id(child)].key)
            except Exception:
                child.logger.exception("Lifecycle component failed to stop key=%s", self._child_specs[id(child)].key)
                raise
        self._registry.clear()
        self._started = False
        self.logger.info("Lifecycle shutdown completed")

    def _add_registration(self, registration: LifecycleRegistration) -> None:
        if self._agent is None:
            raise RuntimeError("AgentLifecycle needs an agent to instantiate registered components")
        if registration.key in self._children_by_key:
            return
        child = registration.component_cls(agent=self._agent)
        self.register(
            child,
            key=registration.key,
            priority=registration.priority,
            before=registration.before,
            after=registration.after,
        )
        self._registered_children[registration.key] = child
        self._registered_specs[registration.key] = registration

    def _mark_changed(self) -> None:
        self._changed = True

    def _configure_child(self, child: AbstractService) -> None:
        if isinstance(child, Manager):
            child.on_change = self._mark_changed

    def _remove_child(self, child: AbstractService) -> None:
        self._children.remove(child)
        spec = self._child_specs.pop(id(child))
        self._children_by_key.pop(spec.key, None)
        if isinstance(child, Manager):
            child.on_change = None
        for key, registered in tuple(self._registered_children.items()):
            if registered is child:
                self._registered_children.pop(key, None)
                self._registered_specs.pop(key, None)
        self._sort_children()

    def _sort_children(self) -> None:
        if len(self._children) < 2:
            return
        self._children = resolve_order(
            self._children,
            aliases=lambda child: self._child_aliases(child),
            priority=lambda child: self._child_specs[id(child)].priority,
            before=lambda child: self._child_specs[id(child)].before,
            after=lambda child: self._child_specs[id(child)].after,
        )

    def _child_aliases(self, child: AbstractService) -> tuple[str, ...]:
        spec = self._child_specs[id(child)]
        cls = type(child)
        return (
            spec.key,
            cls.__name__,
            f"{cls.__module__}.{cls.__qualname__}",
        )

    def _default_key(self, child: AbstractService) -> str:
        cls = type(child)
        base = f"{cls.__module__}.{cls.__qualname__}"
        key = base
        suffix = 2
        while key in self._children_by_key:
            key = f"{base}#{suffix}"
            suffix += 1
        return key

    @staticmethod
    def _registration_is_active(registration: LifecycleRegistration, scope: Iterable[str]) -> bool:
        return any(
            module_name == registration.owner
            or module_name.startswith(registration.owner + ".")
            for module_name in scope
        )


__all__ = ["AgentLifecycle"]
