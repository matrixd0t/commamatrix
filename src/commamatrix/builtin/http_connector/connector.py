# builtin/http_connector/connector.py

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ...components.config import ConfigField
from ...components.connector import Connector
from ...components.dialog import DialogItem, DialogItemType, DialogOrigin, DialogRole
from ...components.hook import OnParsedCtx
from ...components.llm_adapter import StreamDelta

if TYPE_CHECKING:
    from ...core.agent import Agent

http_port = ConfigField[int](
    name="http_port",
    default=8338,
    description="Local HTTP server port for HTTP connector",
)
http_host = ConfigField[str](
    name="http_host",
    default="127.0.0.1",
    description="Local HTTP server host for HTTP connector",
)
http_ui_path = ConfigField[str](
    name="http_ui_path",
    default=str(Path(__file__).parent / "ui" / "index.html"),
    description="Path to the HTTP connector UI HTML file",
)


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
    queue: asyncio.Queue[dict | None] | None = None
    tasks: set[asyncio.Task] = field(default_factory=set)
    background_task: asyncio.Task | None = None
    closed: bool = False


_http_request_context: ContextVar[HttpRequestContext | None] = ContextVar(
    "commamatrix_http_request_context", default=None
)


class HttpConnector(Connector[HttpOrigin]):
    supports_streaming = True

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._port = self.config.get(http_port)
        self._host = self.config.get(http_host)
        self._ui_path = Path(self.config.get(http_ui_path))
        self._server: uvicorn.Server | None = None
        self._bound_port: int | None = None
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._active_requests: dict[str, HttpRequestContext] = {}
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
                async with aiofiles.open(self._ui_path, encoding="utf-8") as f:
                    return HTMLResponse(await f.read())
            return HTMLResponse(
                "<h1>CommaMatrix HTTP UI</h1><p>index.html not found.</p>",
                status_code=404,
            )

        async def health(request: Request) -> Response:
            return JSONResponse({"status": "ok"})

        async def message(request: Request) -> Response:
            return await connector._handle_message(request)

        return Starlette(
            routes=[
                Route("/", index, methods=["GET"]),
                Route("/health", health, methods=["GET"]),
                Route("/api/message", message, methods=["POST"]),
            ]
        )

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
                raise RuntimeError(
                    f"HTTP server failed to start on {self._host}:{self._port}"
                )
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

        for ctx in tuple(self._active_requests.values()):
            self._deactivate_context(ctx)
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
            dialog_items=[
                DialogItem(
                    content=content,
                    item_type=DialogItemType.INPUT,
                    user=f"http:{username}",
                    role=DialogRole.USER,
                    origin=HttpOrigin(session_id=session_id),
                )
            ],
            previous_external_id=data.get("previous_external_id"),
        )

    def _next_external_id(self, session_id: str) -> str:
        return f"http:{session_id}:{uuid.uuid4().hex}"

    def _context_for_origin(self, origin: HttpOrigin) -> HttpRequestContext | None:
        ctx = _http_request_context.get()
        if ctx is None:
            ctx = self._active_requests.get(origin.session_id)
            return ctx if ctx is not None and not ctx.closed else None
        if ctx.closed or ctx.session_id != origin.session_id:
            return None
        if self._active_requests.get(origin.session_id) is not ctx:
            return None
        return ctx

    def _deactivate_context(self, ctx: HttpRequestContext) -> None:
        ctx.closed = True
        if ctx.queue is not None:
            ctx.queue.put_nowait(None)
            if self._sse_queues.get(ctx.session_id) is ctx.queue:
                self._sse_queues.pop(ctx.session_id, None)

        current_task = asyncio.current_task()
        for task in ctx.tasks:
            if task is not current_task and not task.done():
                task.cancel()
        if (
            ctx.background_task is not None
            and ctx.background_task is not current_task
            and not ctx.background_task.done()
        ):
            ctx.background_task.cancel()

        if self._active_requests.get(ctx.session_id) is ctx:
            self._active_requests.pop(ctx.session_id, None)

    def _finish_context(self, ctx: HttpRequestContext) -> None:
        ctx.closed = True
        if ctx.queue is not None:
            ctx.queue.put_nowait(None)
            if self._sse_queues.get(ctx.session_id) is ctx.queue:
                self._sse_queues.pop(ctx.session_id, None)
        if self._active_requests.get(ctx.session_id) is ctx:
            self._active_requests.pop(ctx.session_id, None)

    async def send(self, origin: DialogOrigin, item: DialogItem) -> str:
        if not isinstance(origin, HttpOrigin):
            return ""

        ctx = self._context_for_origin(origin)
        if ctx is None:
            return ""

        ext_id = self._next_external_id(origin.session_id)
        item.external_id = ext_id

        ctx.items.append(item)
        ctx.last_external_id = ext_id

        if ctx.queue is not None:
            await ctx.queue.put(_serialize_item(item))

        return ext_id

    async def send_stream_chunk(self, origin: DialogOrigin, chunk: StreamDelta) -> None:
        if not isinstance(origin, HttpOrigin):
            return
        ctx = self._context_for_origin(origin)
        queue = ctx.queue if ctx is not None else None
        if queue is None and _http_request_context.get() is None:
            queue = self._sse_queues.get(origin.session_id)
        if queue is not None:
            delta_to_item = {"text": "output", "reasoning": "reasoning"}
            await queue.put(
                {
                    "type": "stream_chunk",
                    "delta_type": chunk.delta_type,
                    "item_type": delta_to_item.get(chunk.delta_type, chunk.delta_type),
                    "content": chunk.content,
                    "meta": chunk.meta,
                }
            )

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
            return JSONResponse(
                {"error": "Body must be a JSON object"}, status_code=400
            )

        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            return JSONResponse(
                {"error": "Missing or empty 'content' field"}, status_code=400
            )

        session_id = body.get("session_id") or uuid.uuid4().hex
        username = body.get("username") or "web"
        previous_external_id = body.get("previous_external_id")

        streaming = request.query_params.get("stream", "1") != "0"

        lock = self._get_session_lock(session_id)
        async with lock:
            previous = self._active_requests.get(session_id)
            if previous is not None:
                self._deactivate_context(previous)

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
                    return JSONResponse(
                        {"error": f"Internal error: {exc}"}, status_code=500
                    )
                finally:
                    self._finish_context(ctx)
            else:
                return await self._stream_message(payload, ctx)

    async def _json_message(
        self, payload: dict, ctx: HttpRequestContext, session_id: str
    ) -> Response:
        token = _http_request_context.set(ctx)
        try:
            tasks = await self.agent.handle(payload)
            ctx.tasks.update(tasks)
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            _http_request_context.reset(token)

        for r in results:
            if isinstance(r, BaseException) and not isinstance(
                r, asyncio.CancelledError
            ):
                return JSONResponse(
                    {"error": f"Agent error: {r}"},
                    status_code=500,
                )

        return JSONResponse(
            {
                "session_id": session_id,
                "items": [_serialize_item(item) for item in ctx.items],
                "last_external_id": ctx.last_external_id,
            }
        )

    async def _stream_message(self, payload: dict, ctx: HttpRequestContext) -> Response:
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        ctx.queue = queue
        self._sse_queues[ctx.session_id] = queue

        tasks: list[asyncio.Task] = []

        token = _http_request_context.set(ctx)
        try:
            tasks = await self.agent.handle(payload)
            ctx.tasks.update(tasks)
        except Exception as exc:
            await queue.put({"type": "error", "error": str(exc)})
            await queue.put(None)
            self._finish_context(ctx)
            return StreamingResponse(
                _sse_generator(queue),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        except asyncio.CancelledError:
            await queue.put(None)
            self._deactivate_context(ctx)
            return Response(status_code=499)
        finally:
            _http_request_context.reset(token)

        async def run_and_signal() -> None:
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, BaseException) and not isinstance(
                        r, asyncio.CancelledError
                    ):
                        await queue.put({"type": "error", "error": str(r)})
            except asyncio.CancelledError:
                pass
            finally:
                await queue.put(None)
                self._finish_context(ctx)

        ctx.background_task = asyncio.create_task(run_and_signal())

        return StreamingResponse(
            _sse_generator(queue, lambda: self._deactivate_context(ctx)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


async def _sse_generator(queue: asyncio.Queue[dict | None], on_disconnect=None):
    item_count = 0
    disconnected = False
    while True:
        try:
            item = await queue.get()
        except asyncio.CancelledError:
            disconnected = True
            if on_disconnect is not None:
                on_disconnect()
            break

        if item is None:
            break

        item_count += 1
        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    if disconnected:
        return
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


def _serialize_item(item: DialogItem) -> dict:
    return {
        "item_type": item.item_type.value,
        "role": item.role.value,
        "content": item.content,
        "external_id": item.external_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
