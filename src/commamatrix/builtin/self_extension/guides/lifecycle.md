# Lifecycle Components

Use `@lifecycle_component` for one per-agent component that needs an explicit
place in the ordered `AgentLifecycle`.

```python
from commamatrix import lifecycle_component
from commamatrix.core.classes.service import AbstractService


@lifecycle_component(
    key="project_runtime",
    priority=250,
    after="http_client",
)
class ProjectRuntime(AbstractService):
    async def start(self) -> None:
        pass

    async def refresh(self) -> None:
        pass

    async def stop(self) -> None:
        pass
```

The class must subclass `AbstractService`. Its constructor receives the owning
agent. A lifecycle component is not automatically available through
`agent.services`; use `Service` when that registry behavior is required.

Registrations from `commamatrix.core` and `commamatrix.components` are core
components. Registrations from other modules are instantiated only while the
defining module is in the current agent's extension scope.

## Ordering

`priority` is used among components that are ready to run. `before` and `after`
constraints take precedence over numeric priority. Constraint references may be
names or callables. Unknown targets are ignored; cycles raise
`CyclicConstraintError`.

The library intentionally starts storage before plugin services so a service can
use its declared tables during `start()`. Connector and HTTP server components
are started later in the lifecycle.

## Failure and Removal

Startup is transactional. If a child fails, already-started children are
stopped in reverse order and the registry is cleared. Shutdown also runs in
reverse order.

When an extension is removed or reloaded, registered lifecycle components are
removed from the agent. Active components are stopped before they disappear from
the lifecycle.

Do not use a lifecycle component just to group a small tool or hook. Those
declarations should remain ordinary top-level functions.

See [core/classes/lifecycle_registry.py](../../../core/classes/lifecycle_registry.py),
[core/agent/lifecycle.py](../../../core/agent/lifecycle.py), and
[core/classes/ordering.py](../../../core/classes/ordering.py).

