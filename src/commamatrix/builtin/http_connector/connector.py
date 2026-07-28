# builtin/http_connector/connector.py

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import tzinfo
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiofiles
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ...components.config import ConfigField
from ...components.connector import Connector
from ...components.dialog import DialogItem, DialogItemType, DialogOrigin, DialogRole
from ...components.hook import OnParsedCtx
from ...components.llm_adapter import StreamDelta
from .auth import AuthError, Authorizer

if TYPE_CHECKING:
    from ...core.agent import Agent

http_port = ConfigField[int](name="http_port", default=8338, description="Local HTTP server port for HTTP connector")
http_host = ConfigField[str](name="http_host", default="0.0.0.0", description="HTTP server bind host; use 127.0.0.1 to restrict it to this machine")
http_ui_path = ConfigField[str](name="http_ui_path", default=str(Path(__file__).parent / "ui" / "index.html"), description="Path to the HTTP connector UI HTML file")
http_auth_app_name = ConfigField[str](name="http_auth_app_name", default="commamatrix", description="Application name used to isolate HTTP users")
_http_jwt_secret_cache: str | None = None


def _resolve_jwt_secret() -> str:
    global _http_jwt_secret_cache
    if _http_jwt_secret_cache is not None:
        return _http_jwt_secret_cache
    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        _http_jwt_secret_cache = env_secret
        return env_secret
    secret_path = Path(".jwt_secret")
    if secret_path.exists():
        _http_jwt_secret_cache = secret_path.read_text().strip()
        if _http_jwt_secret_cache:
            return _http_jwt_secret_cache
    secret = secrets.token_urlsafe(32)
    secret_path.write_text(secret)
    _http_jwt_secret_cache = secret
    return secret


http_auth_jwt_secret = ConfigField[str](name="http_auth_jwt_secret", default=_resolve_jwt_secret, description="Secret used to sign HTTP authentication tokens")
http_auth_token_ttl_seconds = ConfigField[int](name="http_auth_token_ttl_seconds", default=24 * 60 * 60, description="HTTP authentication token lifetime in seconds")


class HttpOrigin(DialogOrigin):
    origin_type: str = "http"
    platform: str = "http"
    http_user_id: int


@dataclass(slots=True)
class HTTPSession:
    """One authenticated SSE connection owned by an HTTP user."""

    session_id: str
    user_id: int
    queue: asyncio.Queue[dict | None]
    closed: bool = False


class HttpConnector(Connector[HttpOrigin]):
    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._port = self.config.get(http_port)
        self._host = self.config.get(http_host)
        self._ui_path = Path(self.config.get(http_ui_path))
        self.authorizer = Authorizer(agent=agent, app_name=self.config.get(http_auth_app_name), jwt_secret=self.config.get(http_auth_jwt_secret), token_ttl_seconds=self.config.get(http_auth_token_ttl_seconds))
        self._server: uvicorn.Server | None = None
        self._bound_port: int | None = None
        self._sessions: dict[str, HTTPSession] = {}
        self._sessions_by_user: dict[int, set[str]] = {}
        self._timezones_by_user: dict[int, tzinfo] = {}
        self._app: Starlette | None = None
        self._stream_tasks: dict[str, asyncio.Task] = {}
        self._request_streaming: ContextVar[bool] = ContextVar(f"http_streaming:{id(self)}", default=True)

    @property
    def supports_streaming(self) -> bool:
        """Return the streaming mode of the current HTTP request context."""
        return self._request_streaming.get()

    @staticmethod
    def _debug(message: str) -> None:
        # print(f"[HttpConnector DEBUG] {message}", file=sys.stderr)
        pass

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._bound_port or self._port}"

    @property
    def app(self) -> Starlette:
        if self._app is None:
            self._app = self._build_app()
        assert self._app is not None
        return self._app

    def _build_app(self) -> Starlette:
        async def index(_request: Request) -> Response:
            if self._ui_path.exists():
                async with aiofiles.open(self._ui_path, encoding="utf-8") as file:
                    return HTMLResponse(await file.read())
            return HTMLResponse("<h1>CommaMatrix HTTP UI</h1><p>index.html not found.</p>", status_code=404)

        async def login(request: Request) -> Response:
            try:
                body = await request.json()
                token = await self.authorizer.login(body.get("username", ""), body.get("password", ""))
            except AuthError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=401)
            except Exception:
                return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
            return JSONResponse({"access_token": token, "token_type": "bearer", "expires_in": self.authorizer.token_ttl_seconds})

        async def register(request: Request) -> Response:
            try:
                body = await request.json()
                user = await self.authorizer.register_with_invite(body.get("token", ""), body.get("username", ""), body.get("password", ""))
            except AuthError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            except Exception:
                return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
            return JSONResponse({"id": user.id, "username": user.username}, status_code=201)

        async def invite_page(request: Request) -> Response:
            return await index(request)

        async def health(_request: Request) -> Response:
            return JSONResponse({"status": "ok"})

        @self.authorizer.requires_auth
        async def me(request: Request) -> Response:
            user = request.state.user
            return JSONResponse({"id": user.id, "username": user.username, "app": user.app_name, "is_admin": user.is_admin})

        @self.authorizer.requires_auth
        async def change_password(request: Request) -> Response:
            try:
                body = await request.json()
                await self.authorizer.change_password(request.state.user, body.get("old_password", ""), body.get("new_password", ""))
            except AuthError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            except Exception:
                return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
            return JSONResponse({"status": "ok"})

        @self.authorizer.requires_admin
        async def create_invite(request: Request) -> Response:
            token = await self.authorizer.create_invite()
            url = str(request.base_url).rstrip("/") + "/invite?token=" + token
            return JSONResponse({"url": url})

        @self.authorizer.requires_auth
        async def messages(request: Request) -> Response:
            return await self._handle_message(request)

        @self.authorizer.requires_auth
        async def events(request: Request) -> Response:
            return await self._handle_events(request)

        @self.authorizer.requires_auth
        async def history(request: Request) -> Response:
            return await self._handle_history(request)

        @self.authorizer.requires_auth
        async def cancel_message(request: Request) -> Response:
            stream_id = request.path_params.get("stream_id", "")
            task = self._stream_tasks.pop(stream_id, None)
            if task is None:
                return JSONResponse({"error": "Unknown or already completed stream"}, status_code=404)
            if not task.done():
                task.cancel()
            return JSONResponse({"status": "cancelled"})

        return Starlette(routes=[
            Route("/", index, methods=["GET"]),
            Route("/invite", invite_page, methods=["GET"]),
            Route("/health", health, methods=["GET"]),
            Route("/api/login", login, methods=["POST"]),
            Route("/api/register", register, methods=["POST"]),
            Route("/api/me", me, methods=["GET"]),
            Route("/api/password", change_password, methods=["POST"]),
            Route("/api/invite", create_invite, methods=["POST"]),
            Route("/api/messages", messages, methods=["POST"]),
            Route("/api/messages/{stream_id:str}", cancel_message, methods=["DELETE"]),
            Route("/api/events", events, methods=["GET"]),
            Route("/api/history", history, methods=["GET"]),
            Mount("/ui", app=StaticFiles(directory=str(self._ui_path.parent)), name="http-ui"),
        ])

    async def start(self) -> None:
        if self._server is not None and self._server.started:
            return
        await self.authorizer.init_db()
        config = uvicorn.Config(app=self.app, host=self._host, port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        listener_task = asyncio.create_task(self._server.serve())
        self._listener_task = listener_task
        while not self._server.started:
            if self._server.should_exit:
                await asyncio.gather(listener_task, return_exceptions=True)
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
        await self.authorizer.stop()
        task = getattr(self, "_listener_task", None)
        self._listener_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for session in tuple(self._sessions.values()):
            self._close_session(session)
        self._sessions.clear()
        self._sessions_by_user.clear()
        self._timezones_by_user.clear()

    async def parse(self, data: dict) -> OnParsedCtx | None:
        if data.get("platform") != "http":
            return None
        user_id = int(data["user_id"])
        username = data.get("username", str(user_id))
        timezone_name = data.get("timezone")
        if isinstance(timezone_name, str) and timezone_name:
            try:
                self._timezones_by_user[user_id] = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                self._debug(f"invalid timezone user={user_id} timezone={timezone_name!r}")
        previous_item_id = data.get("previous_item_id")
        self._debug(f"parse user={user_id} previous_item_id={previous_item_id!r}")
        return OnParsedCtx(
            raw=data,
            connector=self,
            agent=self.agent,
            dialog_items=[DialogItem(content=data["content"], item_type=DialogItemType.INPUT, user=f"http:{user_id}", role=DialogRole.USER, origin=HttpOrigin(http_user_id=user_id), previous_item_id=previous_item_id)],
        )

    async def get_user_timezone(self, origin: DialogOrigin) -> tzinfo | None:
        if not isinstance(origin, HttpOrigin):
            return None
        return self._timezones_by_user.get(origin.http_user_id)

    async def get_user_info(self, user: int | str) -> dict[str, int | str] | None:
        found = await self.authorizer.find_user(user)
        if found is None:
            return None
        return {"id": found.id, "username": found.username}

    def _sessions_for_user(self, user_id: int) -> list[HTTPSession]:
        return [self._sessions[session_id] for session_id in self._sessions_by_user.get(user_id, ()) if session_id in self._sessions and not self._sessions[session_id].closed]

    async def _publish(self, user_id: int, event: dict) -> None:
        sessions = self._sessions_for_user(user_id)
        details = ""
        if event.get("type") == "dialog_item":
            details = f" item_id={event.get('item_id')} previous_item_id={event.get('previous_item_id')} external_id={event.get('external_id')!r}"
        self._debug(f"publish user={user_id} type={event.get('type')} sessions={len(sessions)}{details}")
        for session in sessions:
            await session.queue.put(event)

    async def send(self, origin: DialogOrigin, item: DialogItem) -> str:
        return ""

    async def publish_item(self, origin: DialogOrigin, item: DialogItem) -> None:
        if isinstance(origin, HttpOrigin):
            self._debug(f"publish_item user={origin.http_user_id} item_id={item.item_id} item_type={item.item_type.value} previous_item_id={item.previous_item_id} external_id={item.external_id!r}")
            await self._publish(origin.http_user_id, _serialize_item(item))

    async def send_stream_chunk(self, origin: DialogOrigin, chunk: StreamDelta) -> None:
        if not isinstance(origin, HttpOrigin):
            return
        meta = dict(chunk.meta)
        await self._publish(origin.http_user_id, {"type": "stream_chunk", "stream_id": meta.pop("stream_id", None), "item_type": {"text": "output", "reasoning": "reasoning"}.get(chunk.delta_type, chunk.delta_type), "delta_type": chunk.delta_type, "content": chunk.content, "previous_item_id": meta.pop("previous_item_id", None), "meta": meta})

    @asynccontextmanager
    async def typing(self, origin: DialogOrigin) -> AsyncIterator[None]:
        if not isinstance(origin, HttpOrigin):
            yield
            return
        await self._publish(origin.http_user_id, {"type": "typing", "active": True})
        try:
            yield
        finally:
            await self._publish(origin.http_user_id, {"type": "typing", "active": False})

    def _open_session(self, user_id: int) -> HTTPSession:
        session = HTTPSession(session_id=uuid.uuid4().hex, user_id=user_id, queue=asyncio.Queue())
        self._sessions[session.session_id] = session
        self._sessions_by_user.setdefault(user_id, set()).add(session.session_id)
        self._debug(f"open_session user={user_id} session={session.session_id} total_user_sessions={len(self._sessions_by_user[user_id])}")
        return session

    def _close_session(self, session: HTTPSession) -> None:
        if session.closed:
            return
        session.closed = True
        session.queue.put_nowait(None)
        self._sessions.pop(session.session_id, None)
        sessions = self._sessions_by_user.get(session.user_id)
        if sessions is not None:
            sessions.discard(session.session_id)
            if not sessions:
                self._sessions_by_user.pop(session.user_id, None)

    @staticmethod
    def _is_user_origin(item: DialogItem, user_id: int) -> bool:
        return isinstance(item.origin, HttpOrigin) and item.origin.http_user_id == user_id

    async def _validate_parent(self, user_id: int, previous_item_id: int | None) -> bool:
        """Ensure a parent is visible to the authenticated user through its branch."""
        if previous_item_id is None:
            return True
        branch = await self.agent.storage.get_branch(previous_item_id)
        parent = next((item for item in branch if item.item_id == previous_item_id), None)
        parent_is_visible = parent is not None and self._is_user_origin(parent, user_id)
        branch_has_visible = any(self._is_user_origin(item, user_id) for item in branch)
        self._debug(f"validate parent user={user_id} parent={previous_item_id} parent_is_visible={parent_is_visible} branch_has_visible={branch_has_visible} chain={[item.item_id for item in branch]}")
        if not parent_is_visible:
            return False
        return branch_has_visible

    async def _history_for_user(self, user_id: int) -> list[dict]:
        items = await self.agent.storage.get_history()
        by_id = {item.item_id: item for item in items if item.item_id is not None}
        included_ids: set[int] = set()
        for item in items:
            if item.item_id is None or not self._is_user_origin(item, user_id):
                continue
            current_id: int | None = item.item_id
            visited: set[int] = set()
            while current_id is not None and current_id not in visited:
                visited.add(current_id)
                if current_id in included_ids:
                    break
                current = by_id.get(current_id)
                if current is None:
                    break
                included_ids.add(current_id)
                current_id = current.previous_item_id

        result: list[dict] = []
        for item in items:
            if item.item_id is None or item.item_id not in included_ids:
                continue
            if self._is_user_origin(item, user_id):
                result.append(_serialize_item(item))
            else:
                result.append({"item_id": item.item_id, "previous_item_id": item.previous_item_id})
        self._debug(f"history projection user={user_id} full_items={len(items)} returned={len(result)} opaque={sum(1 for item in result if set(item) == {'item_id', 'previous_item_id'})} roots={[item['item_id'] for item in result if item.get('previous_item_id') is None]}")
        return result

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
        previous_item_id = body.get("previous_item_id")
        if previous_item_id is not None and (isinstance(previous_item_id, bool) or not isinstance(previous_item_id, int)):
            return JSONResponse({"error": "'previous_item_id' must be an integer or null"}, status_code=400)
        user = request.state.user
        self._debug(f"POST /api/messages received user={user.id} previous_item_id={previous_item_id!r}")
        if not await self._validate_parent(user.id, previous_item_id):
            return JSONResponse({"error": "The selected branch is not available"}, status_code=403)
        stream_requested = request.query_params.get("stream") == "1"
        self._debug(f"POST /api/messages user={user.id} previous_item_id={previous_item_id!r} stream={stream_requested}")
        payload = {"platform": "http", "user_id": user.id, "username": user.username, "content": content, "previous_item_id": previous_item_id}
        origin_fields = {"http_user_id": user.id}
        known_ids: set[int] = set()
        if not stream_requested:
            before = await self.agent.storage.get_history(origin_type=HttpOrigin, origin_fields=origin_fields)
            known_ids = {item.item_id for item in before if item.item_id is not None}

        async def _run_agent() -> None:
            token = self._request_streaming.set(stream_requested)
            try:
                tasks = await self.agent.handle(payload)
                self._debug(f"agent.handle user={user.id} tasks={len(tasks)} stream={stream_requested}")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
            finally:
                self._request_streaming.reset(token)

        if not stream_requested:
            try:
                await _run_agent()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[HttpConnector] non-stream request failed: {exc}")
                return JSONResponse({"error": str(exc)}, status_code=500)
            after = await self.agent.storage.get_history(origin_type=HttpOrigin, origin_fields=origin_fields)
            items = [item for item in after if item.item_id not in known_ids]
            return JSONResponse({"items": [_serialize_item(item) for item in items]})

        stream_id = uuid.uuid4().hex

        async def _run_wrapper() -> None:
            try:
                await _run_agent()
            except asyncio.CancelledError:
                self._debug(f"stream cancelled stream_id={stream_id} user={user.id}")
            except Exception as exc:
                print(f"[HttpConnector] background stream failed: {exc}")
                await self._publish(user.id, {"type": "error", "error": str(exc), "stream_id": stream_id})
            finally:
                await self._publish(user.id, {"type": "message_done", "stream_id": stream_id})
                self._stream_tasks.pop(stream_id, None)

        wrapper_task = asyncio.create_task(_run_wrapper(), name=f"http-stream:{stream_id}")
        self._stream_tasks[stream_id] = wrapper_task
        return JSONResponse({"stream_id": stream_id}, status_code=202)

    async def _handle_events(self, request: Request) -> Response:
        session = self._open_session(request.state.user.id)
        return StreamingResponse(_sse_generator(session.queue, lambda: self._close_session(session)), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

    async def _handle_history(self, request: Request) -> Response:
        user_id = request.state.user.id
        items = await self._history_for_user(user_id)
        self._debug(f"GET /api/history user={user_id} items={len(items)} ids={[item.get('item_id') for item in items]}")
        return JSONResponse({"items": items})

    def _log_task_error(self, user_id: int, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        print(f"[HttpConnector] background run failed: {error}")
        asyncio.create_task(self._publish(user_id, {"type": "error", "error": str(error)}))


async def _sse_generator(queue: asyncio.Queue[dict | None], on_disconnect=None):
    disconnected = False
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if item is None:
                # print("[HttpConnector DEBUG] SSE yield close", file=sys.stderr)
                break
            # print(f"[HttpConnector DEBUG] SSE yield type={item.get('type')} item_id={item.get('item_id')} previous_item_id={item.get('previous_item_id')}", file=sys.stderr)
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    except asyncio.CancelledError:
        disconnected = True
        # print("[HttpConnector DEBUG] SSE generator cancelled", file=sys.stderr)
    finally:
        if disconnected and on_disconnect is not None:
            on_disconnect()
            # print("[HttpConnector DEBUG] SSE session closed after disconnect", file=sys.stderr)
    if not disconnected:
        yield "data: {\"type\":\"done\"}\n\n"


def _serialize_item(item: DialogItem) -> dict:
    return {"type": "dialog_item", "item_id": item.item_id, "previous_item_id": item.previous_item_id, "item_type": item.item_type.value, "role": item.role.value, "content": item.content, "user": item.user, "origin": item.origin.model_dump(mode="json"), "external_id": item.external_id, "created_at": item.created_at.isoformat() if item.created_at else None}
