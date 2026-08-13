# Configuration

Declare extension configuration fields at module level with `ConfigField`. The
field object itself, not its string name, is the key in `Agent.config`.

```python
import os

from commamatrix import ConfigField


api_key = ConfigField[str](
    name="weather_api_key",
    default=lambda: os.getenv("WEATHER_API_KEY", ""),
    description="API key for the weather service",
)
request_timeout = ConfigField[float](
    name="weather_request_timeout",
    default=20.0,
    description="HTTP timeout in seconds",
)
```

Read and override fields per agent:

```python
from commamatrix import Agent
from my_project.weather import api_key, request_timeout


agent = Agent(
    "main",
    config={api_key: "secret", request_timeout: 10.0},
)

agent.config.set(request_timeout, 15.0)
timeout = agent.config.get(request_timeout)
```

Resolution order is:

1. Per-agent overrides.
2. Per-agent defaults.
3. The field default.

Callable, non-class defaults for non-callable fields are evaluated lazily when
the field is read. For a field typed as `Callable`, the callable itself is the
default value and is not invoked. Class defaults remain class objects. A field
without a default raises a configuration error when its owner first reads it;
creating a `Config` does not validate every plugin field globally.

Keep secrets in environment-backed defaults or host-provided overrides. Never
place API keys in source code, docstrings, metadata, or dialog content.

Fields are visible to the agent only when their declaring module is in the
active extension scope. `agent.config_fields_markdown()` can describe the fields
of active extension modules without printing their values.

When configuration changes affect a long-lived client, apply the change in the
service's `refresh()` or restart the resource explicitly. A configuration field
change does not automatically recreate an unchanged service instance.

See [components/config.py](../../../components/config.py).

