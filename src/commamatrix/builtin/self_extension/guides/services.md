# Services

Use `Service` for an extension-owned runtime object that should be discovered,
started, refreshed, stopped, and exposed through `agent.services`.

```python
from commamatrix import Service
from my_project.configuration import api_key


class WeatherService(Service):
    def __init__(self, agent) -> None:
        super().__init__(agent)
        self._api_key = ""

    async def start(self) -> None:
        self._api_key = self.config.get(api_key)

    async def refresh(self) -> None:
        self._api_key = self.config.get(api_key)

    async def stop(self) -> None:
        self._api_key = ""

    async def forecast(self, city: str) -> dict:
        response = await self.agent.http_client.get(
            "https://example.invalid/weather",
            params={"city": city},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        return response.json()
```

`Service` automatically receives the normal service discovery marker. The
manager creates one instance per discovered service class and registers it by
class and descriptor ID.

Use the shared `agent.http_client` for ordinary HTTP work. It is lifecycle-owned
and must not be closed by an extension. If a service needs a separate client,
create it in `start()` and close it in `stop()`.

## Lifecycle

- `start()` allocates resources when the service becomes active.
- `refresh()` synchronizes state after extension or configuration changes and may be called often.
- `stop()` releases resources when the service is removed or the agent stops.

Keep lifecycle methods idempotent where practical. Make `refresh()` cheap when
there is nothing to change; it is not a one-time constructor hook.

Access a running service through the registry:

```python
service = ctx.run.agent.services.require(WeatherService)
optional = ctx.run.agent.services.get(WeatherService)
```

`require()` raises when the service is not active. A provider such as
`Storage`, `FileStorage`, or `LLMAdapter` also has a dedicated manager and
should not be implemented as a plain `Service`.

## Service vs Lifecycle Component

Use `Service` when the extension owns a discoverable runtime service. Use
`@lifecycle_component` when the extension needs one ordered per-agent component
that participates in the root lifecycle but should not be registered as an
ordinary service. See [lifecycle.md](lifecycle.md).

Do not allocate resources at import time. The service class must be top-level in
an active module, and a package initializer must import the module that defines
it.

See [core/classes/service.py](../../../core/classes/service.py),
[core/classes/manager.py](../../../core/classes/manager.py), and
[components/http_client.py](../../../components/http_client.py).


