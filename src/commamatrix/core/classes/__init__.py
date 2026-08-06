# core/classes/__init__.py

from .descriptor import Descriptor, StaleDescriptorError
from .lifecycle_registry import (
    LifecycleRegistration,
    is_core_component,
    lifecycle_component,
    lifecycle_registrations,
)
from .manager import (
    ActiveServiceInstanceManager,
    InstanceManager,
    Manager,
    ServiceInstanceManager,
    ServiceInstanceRegistry,
)
from .ordering import (
    ConstraintRef,
    CyclicConstraintError,
    normalize_constraint_refs,
    resolve_order,
)
from .service import AbstractService, SERVICE_ATTRIBUTE, Service, ServiceDescriptor
from .source import (
    InvalidationCallback,
    PythonServiceSource,
    PythonSource,
    Source,
    UnavailableSourceError,
)

__all__ = [
    "AbstractService",
    "ActiveServiceInstanceManager",
    "ConstraintRef",
    "CyclicConstraintError",
    "Descriptor",
    "InstanceManager",
    "InvalidationCallback",
    "LifecycleRegistration",
    "Manager",
    "PythonServiceSource",
    "PythonSource",
    "SERVICE_ATTRIBUTE",
    "Service",
    "ServiceDescriptor",
    "ServiceInstanceManager",
    "ServiceInstanceRegistry",
    "Source",
    "StaleDescriptorError",
    "UnavailableSourceError",
    "is_core_component",
    "lifecycle_component",
    "lifecycle_registrations",
    "normalize_constraint_refs",
    "resolve_order",
]
