# core/classes/lifecycle_registry.py

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ...utils import FP
from .ordering import ConstraintRef, normalize_constraint_refs
from .service import AbstractService


@dataclass(frozen=True, slots=True)
class LifecycleRegistration:
    """Declarative registration for an agent-owned lifecycle component."""

    key: str
    component_cls: type[AbstractService]
    priority: int
    before: tuple[str, ...]
    after: tuple[str, ...]
    owner: str


_LIFECYCLE_REGISTRATIONS: dict[str, LifecycleRegistration] = {}


def lifecycle_component(
    component_cls: type[AbstractService] | None = None,
    /,
    *,
    key: str,
    priority: int = 0,
    before: ConstraintRef | Iterable[ConstraintRef] | None = None,
    after: ConstraintRef | Iterable[ConstraintRef] | None = None,
):
    """Register a lifecycle component class for per-agent instantiation."""
    before_norm = normalize_constraint_refs(before)
    after_norm = normalize_constraint_refs(after)

    def decorator(cls: type[AbstractService]) -> type[AbstractService]:
        if not isinstance(cls, type) or not issubclass(cls, AbstractService):
            raise TypeError("Lifecycle components must subclass AbstractService")
        if not key or not key.isidentifier():
            raise ValueError(f"Invalid lifecycle component key: {key!r}")
        _LIFECYCLE_REGISTRATIONS[key] = LifecycleRegistration(
            key=key,
            component_cls=cls,
            priority=priority,
            before=before_norm,
            after=after_norm,
            owner=cls.__module__,
        )
        return cls

    if component_cls is not None:
        return decorator(component_cls)
    return decorator


def lifecycle_registrations() -> tuple[LifecycleRegistration, ...]:
    return tuple(_LIFECYCLE_REGISTRATIONS.values())


def is_core_component(registration: LifecycleRegistration) -> bool:
    return (
        registration.owner == FP
        or registration.owner.startswith(FP + ".core.")
        or registration.owner.startswith(FP + ".components.")
    )


__all__ = [
    "LifecycleRegistration",
    "is_core_component",
    "lifecycle_component",
    "lifecycle_registrations",
]
