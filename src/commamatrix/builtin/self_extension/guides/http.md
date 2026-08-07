# HTTP Server

The agent owns one shared HTTP server exposed as `agent.http_server`. It hosts
the built-in routes and routes or mounts registered by active extensions.

The server normalizes extension paths under `SERVER_ROOT`, which defaults to
`/commamatrix`:

```python
from starlette.responses import JSONResponse

from commamatrix import SERVER_ROOT, Service


class StatusService(Service):
    def __init__(self, agent) -> None:
        super().__init__(agent)
        self._registration = None

    async def start(self) -> None:
        async def status(_request):
            return JSONResponse({"ok": True})

        self._registration = self.agent.http_server.register_route(
            f"{SERVER_ROOT}/status",
            status,
            methods=["GET"],
            name="status",
        )

    async def stop(self) -> None:
        if self._registration is not None:
            self.agent.http_server.unregister(self._registration)
            self._registration = None
```

Register routes from a service or another lifecycle-owned component. A random
function named `register(agent)` is not called automatically by extension
discovery. Unregister routes in `stop()` so reload and removal do not leave
stale endpoints behind.

Available server helpers include `register_route()`, `register_mount()`,
`unregister()`, `base_url`, `url(path)`, and `file_url(file_id)`.

The server's built-in `/commamatrix/handle` endpoint forwards JSON events to
`Agent.handle()`. The built-in HTTP connector adds authentication, UI,
messages, events, and file routes when its extension is active.

## User Frontend

The HTTP connector serves its default frontend from `<CWD>/.commamatrix/ui`.
When the agent starts, missing files are copied from the packaged `ui` template;
existing files are preserved, so workspace edits survive restarts. The important
default files are `index.html`, `app.js`, `styles.css`, and `logo.svg`.

When a user asks to change the HTTP frontend:

1. Inspect and edit the files in `<CWD>/.commamatrix/ui`, not the packaged
   `src/commamatrix/builtin/http_connector/ui` directory.
2. Keep the `/commamatrix` API paths and the `<base href="/commamatrix/ui/">`
   convention unless the route setup is changed deliberately as well.
3. Preserve existing user customizations and add only the missing asset or route
   needed for the requested change.
4. Reload the browser after editing; restart the agent if a missing asset must be
   reseeded or a cached frontend must be refreshed.

## Configuration

`http_host`, `http_port`, and `http_external_url` control binding and public
addresses. The default host is `0.0.0.0`; use `127.0.0.1` for local development
unless public exposure is intentional and protected by authentication, TLS,
reverse-proxy, and network policy.

The server starts only when its optional Starlette and Uvicorn dependencies are
available. HTTP connector functionality has its own optional dependencies and
should be documented separately from the core server.

See [components/server.py](../../../components/server.py),
[components/http_client.py](../../../components/http_client.py), and the
built-in [HTTP connector](../../http_connector/connector.py).

