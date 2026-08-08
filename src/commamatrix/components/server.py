# components/server.py

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..core.classes.lifecycle_registry import lifecycle_component
from ..core.classes.service import AbstractService
from .config import ConfigField

if TYPE_CHECKING:
    from ..core.agent import Agent


SERVER_ROOT = "/commamatrix"

http_port = ConfigField[int](
    name="http_port",
    default=8338,
    description="HTTP http_server port",
)
http_host = ConfigField[str](
    name="http_host",
    default="0.0.0.0",
    description="HTTP http_server bind host; use 127.0.0.1 to restrict access from web",
)
http_external_url = ConfigField[str | None](
    name="http_external_url",
    default=None,
    description="Public base URL used for passing files to external llm api",
)


@dataclass(slots=True)
class _Registration:
    kind: str
    path: str
    endpoint: Callable[..., Any] | None = None
    methods: tuple[str, ...] = ()
    name: str | None = None
    app: Any = None
    route: Any = None


@lifecycle_component(key="http_server", priority=100, after="connector_manager")
class Server(AbstractService):
    """One Starlette application shared by all agent extensions."""

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._host = self.config.get(http_host)
        self._port = self.config.get(http_port)
        self._registrations: list[_Registration] = []
        self._app: Any = None
        self._uvicorn_server: Any = None
        self._listener_task: asyncio.Task | None = None
        self._bound_port: int | None = None

    @property
    def app(self) -> Any:
        if self._app is None:
            self._build_app()
        return self._app

    @property
    def base_url(self) -> str:
        external = self.config.get(http_external_url)
        base = external.rstrip("/") if external else f"http://{self._host}:{self._bound_port or self._port}"
        return base if base.endswith(SERVER_ROOT) else f"{base}{SERVER_ROOT}"

    def url(self, path: str = "") -> str:
        path = "/" + path.lstrip("/") if path else ""
        return f"{self.base_url}{path}"

    def file_url(self, file_id: str) -> str:
        return self.url(f"/files/{quote(file_id, safe='')}")

    def register_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        methods: tuple[str, ...] | list[str] = ("GET",),
        name: str | None = None,
    ) -> _Registration:
        registration = _Registration(
            kind="route",
            path=self._route_path(path),
            endpoint=endpoint,
            methods=tuple(methods),
            name=name,
        )
        self._registrations.append(registration)
        self.logger.debug("HTTP route registered method=%s path=%s", ",".join(registration.methods), registration.path)
        if self._app is not None:
            registration.route = self._make_route(registration)
            self._app.routes.append(registration.route)
        return registration

    add_route = register_route

    def register_mount(self, path: str, app: Any, *, name: str | None = None) -> _Registration:
        registration = _Registration(
            kind="mount",
            path=self._route_path(path),
            name=name,
            app=app,
        )
        self._registrations.append(registration)
        self.logger.debug("HTTP mount registered path=%s", registration.path)
        if self._app is not None:
            registration.route = self._make_mount(registration)
            self._app.routes.append(registration.route)
        return registration

    add_mount = register_mount

    def unregister(self, registration: _Registration) -> None:
        if registration in self._registrations:
            self._registrations.remove(registration)
        if self._app is not None and registration.route is not None:
            try:
                self._app.routes.remove(registration.route)
            except ValueError:
                pass
        registration.route = None
        self.logger.debug("HTTP registration removed path=%s", registration.path)

    def _build_app(self) -> None:
        from starlette.applications import Starlette
        from starlette.routing import Route

        self._app = Starlette(routes=[
            Route(self._route_path("/handle"), self._handle, methods=["POST"], name="handle"),
            Route(self._route_path("/files/{file_id:str}"), self._file, methods=["GET"], name="files"),
            Route(self._route_path("/files/{file_id:str}/content"), self._file, methods=["GET"], name="file-content"),
        ])
        for registration in self._registrations:
            registration.route = self._make_mount(registration) if registration.kind == "mount" else self._make_route(registration)
            self._app.routes.append(registration.route)

    @staticmethod
    def _route_path(path: str) -> str:
        normalized = "/" + str(path).lstrip("/")
        if normalized == SERVER_ROOT or normalized.startswith(f"{SERVER_ROOT}/"):
            return normalized
        return f"{SERVER_ROOT}{normalized}"

    @staticmethod
    def _make_route(registration: _Registration) -> Any:
        from starlette.routing import Route

        return Route(
            registration.path,
            registration.endpoint,
            methods=list(registration.methods),
            name=registration.name,
        )

    @staticmethod
    def _make_mount(registration: _Registration) -> Any:
        from starlette.routing import Mount

        return Mount(registration.path, app=registration.app, name=registration.name)

    async def _handle(self, request: Any) -> Any:
        from starlette.responses import JSONResponse

        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            self.logger.warning("HTTP handle request contained invalid JSON")
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)
        try:
            tasks = await self.agent.handle(payload)
        except Exception as exc:
            self.logger.exception("HTTP handle request failed")
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse({"accepted": len(tasks)}, status_code=202)

    async def _file(self, request: Any) -> Any:
        from starlette.responses import JSONResponse, Response

        from .file_storage import normalize_file_id, read_file

        file_id = normalize_file_id(request.path_params.get("file_id"))
        if file_id is None:
            return JSONResponse({"error": "Invalid file_id"}, status_code=404)
        try:
            file_data = await read_file(file_id, file_storage=self.agent.file_storage)
        except Exception as exc:
            self.logger.exception("HTTP file read failed")
            return JSONResponse({"error": f"Could not read file: {exc}"}, status_code=503)
        if file_data is None:
            return JSONResponse({"error": "File not found"}, status_code=404)
        return Response(
            file_data.data,
            media_type=file_data.mime_type,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(file_data.name)}"},
        )

    async def start(self) -> None:
        if self._uvicorn_server is not None and self._uvicorn_server.started:
            return
        try:
            app = self.app
            import uvicorn
        except ImportError:
            self.logger.warning("HTTP server dependency uvicorn is unavailable")
            return
        self.logger.info("HTTP server starting host=%s port=%d", self._host, self._port)
        config = uvicorn.Config(app=app, host=self._host, port=self._port, log_level="warning")
        self._uvicorn_server = uvicorn.Server(config)
        listener_task = asyncio.create_task(self._uvicorn_server.serve())
        self._listener_task = listener_task
        while not self._uvicorn_server.started:
            if self._uvicorn_server.should_exit:
                await asyncio.gather(listener_task, return_exceptions=True)
                self.logger.error("HTTP server failed to start host=%s port=%d", self._host, self._port)
                raise RuntimeError(f"HTTP http_server failed to start on {self._host}:{self._port}")
            await asyncio.sleep(0.01)
        if self._uvicorn_server.servers:
            self._bound_port = self._uvicorn_server.servers[0].sockets[0].getsockname()[1]
        self.logger.info("HTTP server started host=%s port=%d", self._host, self._bound_port or self._port)

    async def stop(self) -> None:
        self.logger.info("HTTP server stopping")
        server = self._uvicorn_server
        self._uvicorn_server = None
        self._bound_port = None
        if server is not None:
            server.should_exit = True
        task = self._listener_task
        self._listener_task = None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except TimeoutError:
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.logger.info("HTTP server stopped")

