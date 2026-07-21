# builtin/http_connector/connector.py

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ...components.config import ConfigField
from ...components.connector import Connector
from ...components.dialog import DialogItem, DialogItemType, DialogOrigin, DialogRole
from ...components.hook import OnParsedCtx

if TYPE_CHECKING:
    from ...core.agent import Agent

http_port = ConfigField[int](name="http_port", default=8338, description="Local HTTP server port for HTTP connector")
http_host = ConfigField[str](name="http_host", default="127.0.0.1", description="Local HTTP server host for HTTP connector")
http_ui_path = ConfigField[str](name="http_ui_path", default=str(Path(__file__).parent / "ui" / "index.html"), description="Path to the HTTP connector UI HTML file")


class HttpOrigin(DialogOrigin):
    platform: str = "http"
    session_id: str


@dataclass
class HttpRequestContext:
    request_id: str
    session_id: str
    username: str
    items: list[DialogItem] = field(default_factory=list)
    last_external_id: str | None = None


class HttpConnector(Connector[HttpOrigin]):

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._port = self.config.get(http_port)
        self._host = self.config.get(http_host)
        self._ui_path = Path(self.config.get(http_ui_path))
        self._server: uvicorn.Server | None = None
        self._bound_port: int | None = None
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._active_requests: dict[str, HttpRequestContext] = {}
        self._msg_counters: dict[str, int] = {}
        self._last_external_id: dict[str, str] = {}
        self._sse_queues: dict[str, asyncio.Queue[dict | None]] = {}
        self._app: Starlette | None = None

    @property
    def base_url(self) -> str:
        port = self._bound_port or self._port
        return f"http://{self._host}:{port}"

    @property
    def bound_port(self) -> int | None:
        return self._bound_port

    @property
    def app(self) -> Starlette:
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> Starlette:
        connector = self

        async def index(request: Request) -> Response:
            if self._ui_path.exists():
                return HTMLResponse(self._ui_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>CommaMatrix HTTP UI</h1><p>index.html not found.</p>", status_code=404)

        async def health(request: Request) -> Response:
            return JSONResponse({"status": "ok"})

        async def message(request: Request) -> Response:
            return await connector._handle_message(request)

        return Starlette(routes=[
            Route("/", index, methods=["GET"]),
            Route("/health", health, methods=["GET"]),
            Route("/api/message", message, methods=["POST"]),
        ])

    async def start(self) -> None:
        if self._server is not None and self._server.started:
            return

        config = uvicorn.Config(
            app=self.app,
            host=self._host,
            port=self._port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._listener_task = asyncio.create_task(self._server.serve())

        while not self._server.started:
            if self._server.should_exit:
                await asyncio.gather(self._listener_task, return_exceptions=True)
                raise RuntimeError(f"HTTP server failed to start on {self._host}:{self._port}")
            await asyncio.sleep(0.01)

        if hasattr(self._server, "servers") and self._server.servers:
            self._bound_port = self._server.servers[0].sockets[0].getsockname()[1]

        print(f"CommaMatrix web client running on {self.base_url}")

    async def stop(self) -> None:
        server = self._server
        self._server = None
        self._bound_port = None

        if server is not None:
            server.should_exit = True

        task = self._listener_task
        self._listener_task = None

        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        self._active_requests.clear()
        self._session_locks.clear()
        self._sse_queues.clear()

    async def parse(self, data: dict):
        if data.get("platform") != "http":
            return None

        session_id = data["session_id"]
        username = data.get("username", "web")
        content = data["content"]

        return OnParsedCtx(
            raw=data,
            connector=self,
            agent=self.agent,
            dialog_items=[DialogItem(
                content=content,
                item_type=DialogItemType.INPUT,
                user=f"http:{username}",
                role=DialogRole.USER,
                origin=HttpOrigin(session_id=session_id),
            )],
            previous_external_id=data.get("previous_external_id"),
        )

    def _next_external_id(self, session_id: str) -> str:
        counter = self._msg_counters.get(session_id, 0) + 1
        self._msg_counters[session_id] = counter
        ext_id = f"http:{session_id}:{counter}"
        self._last_external_id[session_id] = ext_id
        return ext_id

    async def send(self, origin: DialogOrigin, item: DialogItem) -> str:
        if not isinstance(origin, HttpOrigin):
            return ""

        ctx = self._active_requests.get(origin.session_id)
        if ctx is None:
            return ""

        ext_id = self._next_external_id(origin.session_id)

        ctx.items.append(item)
        ctx.last_external_id = ext_id

        queue = self._sse_queues.get(origin.session_id)
        if queue is not None:
            await queue.put(_serialize_item(item))

        return ext_id

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    async def _handle_message(self, request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        if not isinstance(body, dict):
            return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)

        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            return JSONResponse({"error": "Missing or empty 'content' field"}, status_code=400)

        session_id = body.get("session_id") or uuid.uuid4().hex
        username = body.get("username") or "web"
        previous_external_id = body.get("previous_external_id")

        streaming = request.query_params.get("stream", "1") != "0"

        lock = self._get_session_lock(session_id)
        async with lock:
            request_id = uuid.uuid4().hex
            ctx = HttpRequestContext(
                request_id=request_id,
                session_id=session_id,
                username=username,
            )
            self._active_requests[session_id] = ctx

            payload = {
                "platform": "http",
                "session_id": session_id,
                "username": username,
                "content": content,
                "previous_external_id": previous_external_id,
            }

            if not streaming:
                try:
                    return await self._json_message(payload, ctx, session_id)
                except asyncio.CancelledError:
                    return JSONResponse({"error": "Request cancelled"}, status_code=503)
                except Exception as exc:
                    return JSONResponse({"error": f"Internal error: {exc}"}, status_code=500)
                finally:
                    self._active_requests.pop(session_id, None)
            else:
                return await self._stream_message(payload, session_id)

    async def _json_message(self, payload: dict, ctx: HttpRequestContext, session_id: str) -> Response:
        tasks = await self.agent.handle(payload)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                return JSONResponse(
                    {"error": f"Agent error: {r}"},
                    status_code=500,
                )

        return JSONResponse({
            "session_id": session_id,
            "items": [_serialize_item(item) for item in ctx.items],
            "last_external_id": ctx.last_external_id,
        })

    async def _stream_message(self, payload: dict, session_id: str) -> Response:
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._sse_queues[session_id] = queue

        tasks: list[asyncio.Task] = []

        try:
            tasks = await self.agent.handle(payload)
        except Exception as exc:
            await queue.put({"type": "error", "error": str(exc)})
            await queue.put(None)
            self._active_requests.pop(session_id, None)
            self._sse_queues.pop(session_id, None)
            return StreamingResponse(
                _sse_generator(queue),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        except asyncio.CancelledError:
            await queue.put(None)
            self._active_requests.pop(session_id, None)
            self._sse_queues.pop(session_id, None)
            return Response(status_code=499)

        async def run_and_signal() -> None:
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                        await queue.put({"type": "error", "error": str(r)})
            except asyncio.CancelledError:
                pass
            finally:
                await queue.put(None)
                self._active_requests.pop(session_id, None)
                self._sse_queues.pop(session_id, None)

        asyncio.create_task(run_and_signal())

        return StreamingResponse(
            _sse_generator(queue),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


async def _sse_generator(queue: asyncio.Queue[dict | None]):
    while True:
        try:
            item = await queue.get()
        except asyncio.CancelledError:
            break

        if item is None:
            break

        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


def _serialize_item(item: DialogItem) -> dict:
    return {
        "item_type": item.item_type.value,
        "role": item.role.value,
        "content": item.content,
        "external_id": item.external_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }