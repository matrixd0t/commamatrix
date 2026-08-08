# core/__init__.py

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "Agent": (".agent.agent", "Agent"),
    "AgentLifecycle": (".agent.lifecycle", "AgentLifecycle"),
    "AgentRegistry": (".agent.agent", "AgentRegistry"),
    "AgentRunner": (".agent.runner", "AgentRunner"),
    "agent_by_name": (".agent.agent", "agent_by_name"),
    "agentic_model": (".agent.agent", "agentic_model"),
    "reasoning": (".agent.agent", "reasoning"),
    "get_subagent_by_name": (".agent.agent", "get_subagent_by_name"),
    "plugins_dir": (".agent.agent", "plugins_dir"),
    "AbstractService": (".classes.service", "AbstractService"),
    "ActiveServiceInstanceManager": (".classes.manager", "ActiveServiceInstanceManager"),
    "ConstraintRef": (".classes.ordering", "ConstraintRef"),
    "CyclicConstraintError": (".classes.ordering", "CyclicConstraintError"),
    "Descriptor": (".classes.descriptor", "Descriptor"),
    "InstanceManager": (".classes.manager", "InstanceManager"),
    "InvalidationCallback": (".classes.source", "InvalidationCallback"),
    "LifecycleRegistration": (".classes.lifecycle_registry", "LifecycleRegistration"),
    "Manager": (".classes.manager", "Manager"),
    "MissingExtensionDependencyError": (".extensions", "MissingExtensionDependencyError"),
    "ExtensionOperation": (".extensions", "ExtensionOperation"),
    "ExtensionRuntime": (".extensions", "ExtensionRuntime"),
    "ExtensionRuntimeError": (".extensions", "ExtensionRuntimeError"),
    "ExtensionTarget": (".extensions", "ExtensionTarget"),
    "PythonServiceSource": (".classes.source", "PythonServiceSource"),
    "PythonSource": (".classes.source", "PythonSource"),
    "SERVICE_ATTRIBUTE": (".classes.service", "SERVICE_ATTRIBUTE"),
    "Service": (".classes.service", "Service"),
    "ServiceDescriptor": (".classes.service", "ServiceDescriptor"),
    "ServiceInstanceManager": (".classes.manager", "ServiceInstanceManager"),
    "ServiceInstanceRegistry": (".classes.manager", "ServiceInstanceRegistry"),
    "Source": (".classes.source", "Source"),
    "StaleDescriptorError": (".classes.descriptor", "StaleDescriptorError"),
    "UnavailableSourceError": (".classes.source", "UnavailableSourceError"),
    "discover_plugin_targets": (".extensions", "discover_plugin_targets"),
    "is_core_component": (".classes.lifecycle_registry", "is_core_component"),
    "lifecycle_component": (".classes.lifecycle_registry", "lifecycle_component"),
    "lifecycle_registrations": (".classes.lifecycle_registry", "lifecycle_registrations"),
    "normalize_constraint_refs": (".classes.ordering", "normalize_constraint_refs"),
    "resolve_order": (".classes.ordering", "resolve_order"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    export = _EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = export
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
