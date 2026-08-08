# builtin/http_connector/connector.py

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import tzinfo
from mimetypes import guess_type
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sse_starlette import EventSourceResponse, JSONServerSentEvent, ServerSentEvent
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

from ...components.config import ConfigField
from ...components.connector import Connector
from ...components.dialog import DialogItem, DialogItemType, DialogOrigin, DialogRole
from ...components.file_storage import DataType, normalize_file_id, read_file
from ...components.hook import OnAgentStartCtx, OnParsedCtx, on_agent_start
from ...components.llm_adapter import LLMModalities, StreamDelta
from ...components.server import SERVER_ROOT, http_external_url
from ...utils import _row_value, commamatrix_dir
from .auth import AuthError, Authorizer, InitialAdminCredentials

if TYPE_CHECKING:
    from ...core.agent import Agent

http_ui_path = ConfigField[str | None](name="http_ui_path", default=None, description="Optional explicit path to the HTTP connector UI HTML file; defaults to CWD/commamatrix_dir/ui/index.html")
http_auth_app_name = ConfigField[str](name="http_auth_app_name", default="commamatrix", description="Application name used to isolate HTTP users")
_http_jwt_secret_cache: dict[Path, str] = {}
_BUILTIN_UI_PATH = Path(__file__).parent / "ui"


def _workspace_ui_path(agent: Agent) -> Path:
    return Path.cwd() / agent.config.get(commamatrix_dir) / "ui"


def _copy_missing_ui_files(destination: Path) -> int:
    """Seed a workspace UI without overwriting files customized by the user."""
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for source in _BUILTIN_UI_PATH.rglob("*"):
        if not source.is_file():
            continue
        target = destination / source.relative_to(_BUILTIN_UI_PATH)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


@on_agent_start
async def prepare_http_ui(ctx: OnAgentStartCtx) -> None:
    """Copy missing built-in HTTP UI assets into the workspace UI directory."""
    await asyncio.to_thread(_copy_missing_ui_files, _workspace_ui_path(ctx.agent))


def _resolve_jwt_secret(data_dir: str | os.PathLike[str]) -> str:
    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        return env_secret

    secret_path = (Path(data_dir) / ".jwt_secret").resolve()
    cached_secret = _http_jwt_secret_cache.get(secret_path)
    if cached_secret is not None:
        return cached_secret
    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
        if secret:
            _http_jwt_secret_cache[secret_path] = secret
            return secret

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(32)
    secret_path.write_text(secret, encoding="utf-8")
    _http_jwt_secret_cache[secret_path] = secret
    return secret


http_auth_jwt_secret = ConfigField[str](
    name="http_auth_jwt_secret",
    description="Secret used to sign HTTP authentication tokens; generated in commamatrix_dir/.jwt_secret when omitted",
)
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


@dataclass(frozen=True, slots=True)
class HttpFileRecord:
    file_id: str
    filename: str
    mime_type: str
    size: int
    purpose: str
    created_at: int
    user_id: int


@dataclass(frozen=True, slots=True, init=False)
class HttpStatusMessage:
    text: str | None = None
    code: str | None = None
    severity: str = "yellow"

    def __init__(self, text: str | None = None, severity: str = "yellow", *, code: str | None = None, message: str | None = None) -> None:
        if text is None:
            text = message
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)
        self.__post_init__()

    def __post_init__(self) -> None:
        if not any(isinstance(value, str) and value.strip() for value in (self.code, self.text)):
            raise ValueError("Status message must have code or text")
        if self.severity not in {"yellow", "red"}:
            raise ValueError("Status severity must be 'yellow' or 'red'")

    @property
    def message(self) -> str | None:
        """Return the legacy text alias for configured status messages."""
        return self.text


_NO_PUBLIC_ADDRESS_CODE = "public_address_required"
_NO_PUBLIC_ADDRESS_TEXT = "You cannot upload files for LLM: CommaMatrix is not visible from the Internet."
_OUTPUT_ATTACHMENT_MARKER = re.compile(r"\[(image|file):([^\]\r\n]+)\]", re.IGNORECASE)


class HttpConnector(Connector[HttpOrigin]):
    modalities = LLMModalities(
        input={DataType.TEXT, DataType.IMAGE, DataType.FILE},
        output={DataType.TEXT, DataType.IMAGE, DataType.FILE},
    )

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        configured_ui_path = self.config.get(http_ui_path)
        self._ui_path = Path(configured_ui_path) if configured_ui_path else _workspace_ui_path(agent) / "index.html"
        jwt_secret = (
            self.config.get(http_auth_jwt_secret)
            if http_auth_jwt_secret in self.config
            else _resolve_jwt_secret(self.config.get(commamatrix_dir))
        )
        self.authorizer = Authorizer(agent=agent, app_name=self.config.get(http_auth_app_name), jwt_secret=jwt_secret, token_ttl_seconds=self.config.get(http_auth_token_ttl_seconds))
        self.initial_admin_credentials: InitialAdminCredentials | None = None
        self._sessions: dict[str, HTTPSession] = {}
        self._sessions_by_user: dict[int, set[str]] = {}
        self._timezones_by_user: dict[int, tzinfo] = {}
        self._files: dict[str, HttpFileRecord] = {}
        self._status_messages: list[HttpStatusMessage] = []
        self._history_cache: dict[int, list[DialogItem]] = {}
        self._stream_tasks: dict[str, asyncio.Task] = {}
        self._stream_users: dict[str, int] = {}
        self._route_handles: list[object] = []
        self._request_streaming: ContextVar[bool] = ContextVar(f"http_streaming:{id(self)}", default=True)
        self._register_routes()
        self.logger.debug("HTTP connector routes registered count=%d", len(self._route_handles))

    @property
    def supports_streaming(self) -> bool:
        """Return the streaming mode of the current HTTP request context."""
        return self._request_streaming.get()

    @property
    def app(self) -> Any:
        """Return the shared Starlette application hosting this connector's routes."""
        return self.agent.http_server.app

    @property
    def base_url(self) -> str:
        return self.agent.http_server.base_url

    def _register_routes(self) -> None:
        server = self.agent.http_server
        auth = self.authorizer.requires_auth
        admin = self.authorizer.requires_admin
        self._route_handles.extend([
            server.register_route("/", self._index),
            server.register_route("/invite", self._index),
            server.register_route("/health", self._health),
            server.register_route("/api/login", self._login, methods=["POST"]),
            server.register_route("/api/register", self._register, methods=["POST"]),
            server.register_route("/api/me", auth(self._me)),
            server.register_route("/api/status", auth(self._status)),
            server.register_route("/api/password", auth(self._change_password), methods=["POST"]),
            server.register_route("/api/username", auth(self._change_username), methods=["POST"]),
            server.register_route("/api/invite", admin(self._create_invite), methods=["POST"]),
            server.register_route("/api/messages", auth(self._handle_message), methods=["POST"]),
            server.register_route("/api/messages/{stream_id:str}", auth(self._cancel_message), methods=["DELETE"]),
            server.register_route("/v1/files", auth(self._handle_file_upload), methods=["POST"]),
            server.register_route("/api/files", auth(self._handle_file_upload), methods=["POST"]),
            server.register_route("/v1/files/{file_id:str}/content", auth(self._handle_file_content)),
            server.register_route("/api/files/{file_id:str}/content", auth(self._handle_file_content)),
            server.register_route("/v1/files/{file_id:str}", auth(self._handle_file_metadata)),
            server.register_route("/api/files/{file_id:str}", auth(self._handle_file_metadata)),
            server.register_route("/api/events", auth(self._handle_events)),
            server.register_route("/api/history", auth(self._handle_history)),
            server.register_mount("/ui", StaticFiles(directory=str(self._ui_path.parent), check_dir=False), name="http-ui"),
        ])

    async def _index(self, _request: Request) -> Response:
        if self._ui_path.exists():
            content = await asyncio.to_thread(self._ui_path.read_text, encoding="utf-8")
            return HTMLResponse(content)
        return HTMLResponse("<h1>CommaMatrix HTTP UI</h1><p>index.html not found.</p>", status_code=404)

    async def _login(self, request: Request) -> Response:
        try:
            body = await request.json()
            token = await self.authorizer.login(body.get("username", ""), body.get("password", ""))
        except AuthError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)
        except Exception:  # noqa: BLE001
            return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
        return JSONResponse({"access_token": token, "token_type": "bearer", "expires_in": self.authorizer.token_ttl_seconds})

    async def _register(self, request: Request) -> Response:
        try:
            body = await request.json()
            user = await self.authorizer.register_with_invite(body.get("token", ""), body.get("username", ""), body.get("password", ""))
        except AuthError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except Exception:  # noqa: BLE001
            return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
        return JSONResponse({"id": user.id, "username": user.username}, status_code=201)

    async def _health(self, _request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def _me(self, request: Request) -> Response:
        user = request.state.user
        return JSONResponse({"id": user.id, "username": user.username, "app": user.app_name, "is_admin": user.is_admin})

    @property
    def file_upload_allowed(self) -> bool:
        return bool(self.config.get(http_external_url))

    @property
    def status_messages(self) -> tuple[HttpStatusMessage, ...]:
        return tuple(self._status_messages)

    def set_status_messages(self, messages: Iterable[HttpStatusMessage | Mapping[str, object] | str]) -> None:
        normalized: list[HttpStatusMessage] = []
        for value in messages:
            if isinstance(value, HttpStatusMessage):
                normalized.append(value)
                continue
            if isinstance(value, str):
                normalized.append(HttpStatusMessage(value))
                continue
            if isinstance(value, Mapping):
                text = value.get("text", value.get("message"))
                code = value.get("code")
                severity = value.get("severity", "yellow")
                if (isinstance(text, str) or isinstance(code, str)) and isinstance(severity, str):
                    normalized.append(HttpStatusMessage(text=text, code=code if isinstance(code, str) else None, severity=severity))
        self._status_messages = normalized

    def _status_payload(self) -> dict[str, object]:
        messages = []
        if not self.file_upload_allowed:
            messages.append({"code": _NO_PUBLIC_ADDRESS_CODE, "text": _NO_PUBLIC_ADDRESS_TEXT, "severity": "yellow"})
        for item in self._status_messages:
            message: dict[str, str] = {"severity": item.severity}
            if item.code:
                message["code"] = item.code
            if item.text:
                message["text"] = item.text
            messages.append(message)
        return {"messages": messages, "file_upload_allowed": self.file_upload_allowed, "poll_after": 3}

    async def _status(self, _request: Request) -> Response:
        return JSONResponse(self._status_payload())

    def _file_upload_blocked(self) -> JSONResponse:
        return JSONResponse({"code": _NO_PUBLIC_ADDRESS_CODE, "text": _NO_PUBLIC_ADDRESS_TEXT}, status_code=403)

    async def _change_password(self, request: Request) -> Response:
        try:
            body = await request.json()
            await self.authorizer.change_password(request.state.user, body.get("old_password", ""), body.get("new_password", ""))
        except AuthError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except Exception:  # noqa: BLE001
            return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
        return JSONResponse({"status": "ok"})

    async def _change_username(self, request: Request) -> Response:
        try:
            body = await request.json()
            user = await self.authorizer.change_username(request.state.user, body.get("username", ""))
        except AuthError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except Exception:  # noqa: BLE001
            return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)
        request.state.user = user
        return JSONResponse({"status": "ok", "username": user.username})

    async def _create_invite(self, _request: Request) -> Response:
        token = await self.authorizer.create_invite()
        base_url = self.base_url.rstrip("/")
        parsed = urlparse(base_url)
        if parsed.hostname == "0.0.0.0":
            base_url = parsed._replace(netloc=parsed.netloc.replace("0.0.0.0", "127.0.0.1", 1)).geturl().rstrip("/")
        url = f"{base_url}/invite?token={token}"
        return JSONResponse({"url": url})

    async def _cancel_message(self, request: Request) -> Response:
        stream_id = request.path_params.get("stream_id", "")
        task = self._stream_tasks.pop(stream_id, None)
        if task is None:
            return JSONResponse({"error": "Unknown or already completed stream"}, status_code=404)
        if not task.done():
            task.cancel()
        return JSONResponse({"status": "cancelled"})

    def _unregister_routes(self) -> None:
        for registration in self._route_handles:
            self.agent.http_server.unregister(registration)
        self._route_handles.clear()

    async def start(self) -> None:
        try:
            self.initial_admin_credentials = await self.authorizer.init_db()
        except BaseException:
            self.logger.exception("HTTP connector failed to initialize authentication")
            self._unregister_routes()
            raise
        self.logger.info("HTTP connector started")

    async def stop(self) -> None:
        self.logger.info("HTTP connector stopping sessions=%d streams=%d", len(self._sessions), len(self._stream_tasks))
        await self.authorizer.stop()
        self._unregister_routes()
        for task in self._stream_tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._stream_tasks.values(), return_exceptions=True)
        self._stream_tasks.clear()
        self._stream_users.clear()
        for session in tuple(self._sessions.values()):
            self._close_session(session)
        self._sessions.clear()
        self._sessions_by_user.clear()
        self._timezones_by_user.clear()
        self._history_cache.clear()
        self.logger.info("HTTP connector stopped")

    async def parse(self, data: dict) -> OnParsedCtx | None:
        if data.get("platform") != "http":
            return None
        user_id = int(data["user_id"])
        timezone_name = data.get("timezone")
        if isinstance(timezone_name, str) and timezone_name:
            try:
                self._timezones_by_user[user_id] = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                pass
        previous_item_id = data.get("previous_item_id")
        content = data.get("content", "")
        origin = HttpOrigin(http_user_id=user_id)
        dialog_items: list[DialogItem] = []
        if isinstance(content, str) and content:
            dialog_items.append(DialogItem(content=content, item_type=DialogItemType.INPUT, user=f"http:{user_id}", role=DialogRole.USER, origin=origin, previous_item_id=previous_item_id))
        attachments = data.get("attachments")
        if isinstance(attachments, list):
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                kind = attachment.get("kind")
                if kind not in {"image", "file"}:
                    continue
                field_name = kind
                dialog_items.append(DialogItem(
                    content=json.dumps({field_name: {
                        "ref": attachment.get("file_id"),
                        "ext": attachment.get("ext", ""),
                        "name": attachment.get("name", attachment.get("file_id", "file")),
                        "mime_type": attachment.get("mime_type", "application/octet-stream"),
                        "url": attachment.get("url"),
                        "size": attachment.get("size"),
                    }}, ensure_ascii=False),
                    item_type=DialogItemType.IMAGE_INPUT if kind == "image" else DialogItemType.FILE_INPUT,
                    user=f"http:{user_id}",
                    role=DialogRole.USER,
                    origin=origin,
                    previous_item_id=previous_item_id,
                ))
        self.logger.debug("HTTP event parsed user_id=%d items=%d attachments=%d", user_id, len(dialog_items), len(attachments) if isinstance(attachments, list) else 0)
        return OnParsedCtx(raw=data, connector=self, agent=self.agent, dialog_items=dialog_items)

    async def get_user_timezone(self, origin: DialogOrigin) -> tzinfo | None:
        if not isinstance(origin, HttpOrigin):
            return None
        return self._timezones_by_user.get(origin.http_user_id)

    async def get_user_name(self, origin: DialogOrigin) -> str | None:
        if not isinstance(origin, HttpOrigin):
            return None
        found = await self.authorizer.find_user(origin.http_user_id)
        return found.username if found is not None else None

    async def _find_name_record(self, name: str) -> tuple[object, str | None] | None:
        try:
            rows = await self.agent.storage.execute(
                "SELECT user, name, alternatives FROM commamatrix_user_names"
            )
        except Exception as exc:
            if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
                return None
            raise
        normalized = name.casefold()
        for row in rows:
            current_name = _row_value(row, "name")
            if isinstance(current_name, str) and current_name.casefold() == normalized:
                return row, None
            try:
                alternatives = json.loads(_row_value(row, "alternatives") or "[]")
            except (TypeError, ValueError):
                alternatives = []
            if not isinstance(alternatives, list):
                continue
            if any(isinstance(value, str) and value.casefold() == normalized for value in alternatives):
                return row, name
        return None

    async def get_user_info(self, user: int | str) -> dict[str, object] | None:
        matched_name: str | None = None
        lookup: int | str = user
        search_name = user
        if isinstance(user, str):
            lookup = user.strip()
            if ":" in lookup:
                platform, _, identifier = lookup.partition(":")
                if platform.casefold() == "http":
                    lookup = identifier.strip()
                    search_name = lookup
            try:
                lookup = int(lookup)
            except ValueError:
                pass
        found = await self.authorizer.find_user(lookup)
        if found is None and isinstance(user, str):
            name_record = await self._find_name_record(str(search_name).strip())
            if name_record is not None:
                row, matched_name = name_record
                stored_user = _row_value(row, "user")
                if isinstance(stored_user, str):
                    found = await self.authorizer.find_user(stored_user.removeprefix("http:"))
        if found is None:
            return None
        result: dict[str, object] = {"id": found.id, "username": found.username}
        if matched_name is not None:
            result["matched_name"] = matched_name
            result["name_changed"] = matched_name.casefold() != found.username.casefold()
        return result

    def _sessions_for_user(self, user_id: int) -> list[HTTPSession]:
        return [self._sessions[session_id] for session_id in self._sessions_by_user.get(user_id, ()) if session_id in self._sessions and not self._sessions[session_id].closed]

    async def _publish(self, user_id: int, event: dict) -> None:
        sessions = self._sessions_for_user(user_id)
        for session in sessions:
            await session.queue.put(event)

    async def send(self, origin: DialogOrigin, item: DialogItem) -> str:
        if isinstance(origin, HttpOrigin) and item.item_type is DialogItemType.OUTPUT:
            await self._prepare_output_attachments(item)
        return ""

    async def _prepare_output_attachments(self, item: DialogItem) -> None:
        matches = tuple(_OUTPUT_ATTACHMENT_MARKER.finditer(item.content))
        if not matches:
            return

        attachments = [
            await self._resolve_output_attachment(
                DataType(match.group(1).lower()),
                match.group(2).strip(),
            )
            for match in matches
        ]
        item.content = re.sub(
            r"[ \t]+([,.;:!?])",
            r"\1",
            _OUTPUT_ATTACHMENT_MARKER.sub("", item.content),
        ).strip()
        http_meta = item.meta.get("http")
        if not isinstance(http_meta, dict):
            http_meta = {}
            item.meta["http"] = http_meta
        http_meta["attachments"] = attachments

    async def _resolve_output_attachment(self, modality: DataType, ref: str) -> dict:
        attachment: dict = {
            "kind": modality.value,
            "name": Path(ref).name or ref,
        }
        try:
            if not ref:
                raise ValueError("Attachment reference is empty")

            path = Path(ref).expanduser()
            if path.is_file() or path.is_absolute():
                source = str(path.resolve())
            elif normalize_file_id(ref) is not None:
                source = ref
                attachment["ref"] = ref
            else:
                raise ValueError("Attachment reference must be a file ID or a local path")

            file_data = await read_file(
                source,
                file_storage=self.agent.file_storage,
                http_client=self.agent.http_client,
                name=path.name,
                ext=path.suffix,
                content_type=modality,
                make_url=True,
            )
            if file_data is None:
                raise FileNotFoundError(f"File not found: {ref}")

            attachment.update(
                {
                    "name": file_data.name,
                    "mime_type": file_data.mime_type,
                    "size": len(file_data.data),
                    "url": self._browser_file_url(file_data.url),
                    "ext": Path(file_data.name).suffix.lstrip("."),
                }
            )
        except Exception as exc:  # noqa: BLE001
            attachment["error"] = str(exc)
        return attachment

    async def publish_item(self, origin: DialogOrigin, item: DialogItem) -> None:
        if isinstance(origin, HttpOrigin):
            self._cache_item(item)
            await self._publish(origin.http_user_id, _serialize_item(item))

    async def send_stream_chunk(self, origin: DialogOrigin, chunk: StreamDelta) -> None:
        if not isinstance(origin, HttpOrigin):
            return
        meta = {key: value for key, value in chunk.meta.items() if key != "llm"}
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
        for stream_id, stream_user_id in self._stream_users.items():
            if stream_user_id == user_id and stream_id in self._stream_tasks:
                session.queue.put_nowait({"type": "stream_started", "stream_id": stream_id})
        self._sessions[session.session_id] = session
        self._sessions_by_user.setdefault(user_id, set()).add(session.session_id)
        self.logger.debug("HTTP event session opened user_id=%d active_sessions=%d", user_id, len(self._sessions))
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
                self._history_cache.pop(session.user_id, None)
        self.logger.debug("HTTP event session closed user_id=%d active_sessions=%d", session.user_id, len(self._sessions))

    @staticmethod
    def _is_user_origin(item: DialogItem, user_id: int) -> bool:
        return isinstance(item.origin, HttpOrigin) and item.origin.http_user_id == user_id

    async def _validate_parent(self, user_id: int, previous_item_id: int | None) -> bool:
        """Ensure a parent is visible to the authenticated user through its branch."""
        if previous_item_id is None:
            return True
        branch = await self.agent.storage.get_branch(previous_item_id)
        parent_is_visible = any(item.item_id == previous_item_id and self._is_user_origin(item, user_id) for item in branch)
        branch_has_visible = any(self._is_user_origin(item, user_id) for item in branch)
        if not parent_is_visible:
            return False
        return branch_has_visible

    def _cache_item(self, item: DialogItem) -> None:
        if item.item_id is None or not isinstance(item.origin, HttpOrigin):
            return
        cached = self._history_cache.get(item.origin.http_user_id)
        if cached is None:
            return
        for index, cached_item in enumerate(cached):
            if cached_item.item_id == item.item_id:
                cached[index] = item
                break
        else:
            cached.append(item)
            cached.sort(key=lambda value: value.item_id or 0)

    async def _history_for_user(self, user_id: int) -> list[DialogItem]:
        cached = self._history_cache.get(user_id)
        if cached is not None:
            return cached

        items = await self.agent.storage.get_history(origin_type=HttpOrigin, origin_fields={"http_user_id": user_id})
        by_id = {item.item_id: item for item in items if item.item_id is not None}
        for item in items:
            if item.item_id is None or item.previous_item_id is None or item.previous_item_id in by_id:
                continue
            for ancestor in await self.agent.storage.get_branch(item.item_id):
                if ancestor.item_id is not None:
                    by_id.setdefault(ancestor.item_id, ancestor)

        cached = sorted(by_id.values(), key=lambda item: item.item_id or 0)
        self._history_cache[user_id] = cached
        return cached

    @staticmethod
    def _history_tree(items: list[DialogItem], head_id: int | None) -> list[DialogItem]:
        if head_id is None:
            return []
        by_id = {item.item_id: item for item in items if item.item_id is not None}
        head = by_id.get(head_id)
        if head is None:
            return []

        root_id = head.item_id
        current = head
        visited: set[int] = set()
        while current.item_id is not None and current.item_id not in visited:
            visited.add(current.item_id)
            parent = by_id.get(current.previous_item_id)
            if parent is None:
                break
            root_id = parent.item_id
            current = parent

        children: dict[int, list[int]] = {}
        for item in items:
            if item.item_id is None or item.previous_item_id not in by_id:
                continue
            children.setdefault(item.previous_item_id, []).append(item.item_id)

        result: list[DialogItem] = []
        stack = [root_id]
        seen: set[int] = set()
        while stack:
            item_id = stack.pop()
            if item_id in seen:
                continue
            seen.add(item_id)
            item = by_id.get(item_id)
            if item is None:
                continue
            result.append(item)
            stack.extend(children.get(item_id, ()))
        result.sort(key=lambda item: item.item_id or 0)
        return result

    def _branch_preview(self, items: list[DialogItem], root: DialogItem, user_id: int) -> str:
        if root.item_id is None:
            return root.content
        by_id = {item.item_id: item for item in items if item.item_id is not None}
        children: dict[int, list[int]] = {}
        for item in items:
            if item.item_id is None or item.previous_item_id not in by_id:
                continue
            children.setdefault(item.previous_item_id, []).append(item.item_id)

        branch: list[DialogItem] = []
        stack = [root.item_id]
        seen: set[int] = set()
        while stack:
            item_id = stack.pop()
            if item_id in seen:
                continue
            seen.add(item_id)
            item = by_id.get(item_id)
            if item is None:
                continue
            branch.append(item)
            stack.extend(children.get(item_id, ()))
        branch.sort(key=lambda item: (item.created_at, item.item_id or 0))

        message_types = {
            DialogItemType.INPUT,
            DialogItemType.IMAGE_INPUT,
            DialogItemType.FILE_INPUT,
            DialogItemType.OUTPUT,
            DialogItemType.IMAGE_OUTPUT,
            DialogItemType.FILE_OUTPUT,
        }
        messages = [
            item
            for item in branch
            if self._is_user_origin(item, user_id)
            and item.role in {DialogRole.USER, DialogRole.ASSISTANT}
            and item.item_type in message_types
        ]
        return (messages or branch)[0].content if messages or branch else ""

    def _history_heads(self, items: list[DialogItem], user_id: int) -> list[tuple[DialogItem, DialogItem]]:
        by_id = {item.item_id: item for item in items if item.item_id is not None}
        visible = [item for item in items if item.item_id is not None and self._is_user_origin(item, user_id)]
        children: dict[int, set[int]] = {}
        for item in items:
            if item.item_id is None or item.previous_item_id not in by_id or not self._is_user_origin(item, user_id):
                continue
            children.setdefault(item.previous_item_id, set()).add(item.item_id)

        roots: list[DialogItem] = []
        root_by_id: dict[int, DialogItem] = {}
        for item in visible:
            current_id = item.previous_item_id
            visited: set[int] = set()
            visible_parent = False
            while current_id is not None and current_id not in visited:
                visited.add(current_id)
                parent = by_id.get(current_id)
                if parent is None:
                    break
                if self._is_user_origin(parent, user_id):
                    visible_parent = True
                    break
                current_id = parent.previous_item_id
            if visible_parent:
                continue
            roots.append(item)
            root_by_id[item.item_id] = item

        latest_by_root: dict[int, DialogItem] = {}
        for item in visible:
            if children.get(item.item_id):
                continue
            current = item
            visited: set[int] = set()
            root_id: int | None = None
            while current.item_id is not None and current.item_id not in visited:
                visited.add(current.item_id)
                if current.item_id in root_by_id:
                    root_id = current.item_id
                    break
                parent = by_id.get(current.previous_item_id)
                if parent is None:
                    break
                current = parent
            if root_id is None:
                continue
            latest = latest_by_root.get(root_id)
            if latest is None or (item.item_id or 0) > (latest.item_id or 0):
                latest_by_root[root_id] = item

        result = [(latest_by_root[root.item_id], root) for root in roots if root.item_id in latest_by_root]
        result.sort(key=lambda pair: pair[0].item_id or 0, reverse=True)
        return result

    def _serialize_history_item(self, item: DialogItem, user_id: int) -> dict:
        if self._is_user_origin(item, user_id):
            return _serialize_item(item)
        return {"item_id": item.item_id, "previous_item_id": item.previous_item_id}

    def _file_content_url(self, file_id: str) -> str:
        return f"{SERVER_ROOT}/files/{quote(file_id, safe='')}"

    @staticmethod
    def _browser_file_url(url: str | None) -> str | None:
        if not url:
            return None
        path = urlparse(url).path
        return path if path.startswith(f"{SERVER_ROOT}/files/") else url

    def _file_payload(self, record: HttpFileRecord) -> dict:
        content_url = self._file_content_url(record.file_id)
        return {
            "id": record.file_id,
            "file_id": record.file_id,
            "object": "file",
            "type": "file",
            "filename": record.filename,
            "name": record.filename,
            "bytes": record.size,
            "size_bytes": record.size,
            "mime_type": record.mime_type,
            "purpose": record.purpose,
            "status": "processed",
            "created_at": record.created_at,
            "url": content_url,
            "content_url": content_url,
        }

    @staticmethod
    def _fallback_file_record(file_id: str, size: int, user_id: int) -> HttpFileRecord:
        filename = file_id
        return HttpFileRecord(
            file_id=file_id,
            filename=filename,
            mime_type=guess_type(filename)[0] or "application/octet-stream",
            size=size,
            purpose="user_data",
            created_at=0,
            user_id=user_id,
        )

    async def _handle_file_upload(self, request: Request) -> Response:
        if not self.file_upload_allowed:
            return self._file_upload_blocked()
        try:
            form = await request.form()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"Invalid multipart form: {exc}"}, status_code=400)

        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return JSONResponse({"error": "Missing multipart 'file' field"}, status_code=400)
        filename = str(getattr(upload, "filename", "") or "file").replace("\\", "/")
        filename = Path(filename).name or "file"
        try:
            data = await upload.read()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"Could not read uploaded file: {exc}"}, status_code=400)
        if not isinstance(data, bytes):
            return JSONResponse({"error": "Uploaded file data is invalid"}, status_code=400)

        mime_type = str(getattr(upload, "content_type", "") or "").split(";", 1)[0].strip().lower()
        mime_type = mime_type or guess_type(filename)[0] or "application/octet-stream"
        extension = Path(filename).suffix.lstrip(".") or None
        purpose = str(form.get("purpose") or "user_data")
        try:
            file_id = await self.agent.file_storage.save(data, ext=extension)
        except Exception as exc:
            self.logger.exception("HTTP file upload storage failed user_id=%d", request.state.user.id)
            return JSONResponse({"error": f"Could not save file: {exc}"}, status_code=503)

        record = HttpFileRecord(
            file_id=file_id,
            filename=filename,
            mime_type=mime_type,
            size=len(data),
            purpose=purpose,
            created_at=int(time.time()),
            user_id=request.state.user.id,
        )
        self._files[file_id] = record
        self.logger.info("HTTP file uploaded user_id=%d size=%d", request.state.user.id, len(data))
        return JSONResponse(self._file_payload(record))

    def _resolve_file_id(self, request: Request) -> str | Response:
        file_id = normalize_file_id(request.path_params.get("file_id"))
        return file_id if file_id is not None else JSONResponse({"error": "Invalid file_id"}, status_code=404)

    async def _read_file(self, file_id: str) -> bytes | Response:
        try:
            data = await self.agent.file_storage.get(file_id)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"Could not read file: {exc}"}, status_code=503)
        return data if data is not None else JSONResponse({"error": "File not found"}, status_code=404)

    async def _handle_file_metadata(self, request: Request) -> Response:
        file_id = self._resolve_file_id(request)
        if isinstance(file_id, Response):
            return file_id
        record = self._files.get(file_id)
        if record is None:
            data = await self._read_file(file_id)
            if isinstance(data, Response):
                return data
            record = self._fallback_file_record(file_id, len(data), request.state.user.id)
        return JSONResponse(self._file_payload(record))

    async def _handle_file_content(self, request: Request) -> Response:
        file_id = self._resolve_file_id(request)
        if isinstance(file_id, Response):
            return file_id
        data = await self._read_file(file_id)
        if isinstance(data, Response):
            return data
        record = self._files.get(file_id) or self._fallback_file_record(file_id, len(data), request.state.user.id)
        return Response(
            data,
            media_type=record.mime_type,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(record.filename)}"},
        )

    async def _user_history(self, user_id: int) -> list[DialogItem]:
        return await self._history_for_user(user_id)

    async def _normalize_attachments(self, value: object) -> tuple[list[dict], str | None]:
        if value is None:
            return [], None
        if not isinstance(value, list):
            return [], "'attachments' must be an array"

        normalized: list[dict] = []
        for attachment in value:
            if not isinstance(attachment, dict):
                return [], "Each attachment must be an object"
            file_id = normalize_file_id(attachment.get("file_id") or attachment.get("id"))
            external_url = attachment.get("url")
            if file_id is None and isinstance(external_url, str) and external_url:
                parsed_url = urlparse(external_url)
                if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                    return [], "External attachment URL must be an absolute HTTP or HTTPS URL"
                declared_type = str(attachment.get("type") or attachment.get("kind") or "").lower()
                mime_value = attachment.get("mime_type")
                mime_type = mime_value if isinstance(mime_value, str) and mime_value else guess_type(parsed_url.path)[0] or "application/octet-stream"
                if declared_type in {"image", "image_input"} or mime_type.startswith("image/"):
                    kind = "image"
                else:
                    kind = "file"
                filename_value = attachment.get("filename") or attachment.get("name")
                filename = filename_value if isinstance(filename_value, str) and filename_value else Path(parsed_url.path).name or external_url
                ext = attachment.get("ext")
                if not isinstance(ext, str) or not ext:
                    ext = Path(filename).suffix.lstrip(".")
                size = attachment.get("size")
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    size = None
                normalized.append({
                    "kind": kind,
                    "file_id": None,
                    "name": filename,
                    "mime_type": mime_type,
                    "ext": ext,
                    "url": external_url,
                    "size": size,
                })
                continue
            if file_id is None:
                return [], "Each attachment requires a valid file_id or external URL"
            try:
                data = await self.agent.file_storage.get(file_id)
            except Exception as exc:  # noqa: BLE001
                return [], f"Could not read file_id {file_id!r}: {exc}"
            if data is None:
                return [], f"File not found: {file_id}"

            record = self._files.get(file_id)
            declared_type = str(attachment.get("type") or attachment.get("kind") or "").lower()
            if declared_type in {"image", "image_input"}:
                kind = "image"
            elif declared_type in {"file", "file_input"}:
                kind = "file"
            elif record is not None and record.mime_type.startswith("image/"):
                kind = "image"
            else:
                kind = "image" if str(attachment.get("mime_type") or "").startswith("image/") else "file"

            filename_value = attachment.get("filename") or attachment.get("name")
            if isinstance(filename_value, str) and filename_value:
                filename = filename_value
            elif record is not None:
                filename = record.filename
            else:
                filename = file_id
            mime_value = attachment.get("mime_type")
            if isinstance(mime_value, str) and mime_value:
                mime_type = mime_value
            elif record is not None:
                mime_type = record.mime_type
            else:
                mime_type = guess_type(filename)[0] or "application/octet-stream"
            ext = attachment.get("ext")
            if not isinstance(ext, str) or not ext:
                ext = Path(filename).suffix.lstrip(".")
            normalized.append({
                "kind": kind,
                "file_id": file_id,
                "name": filename,
                "mime_type": mime_type,
                "ext": ext,
                "url": self._file_content_url(file_id),
                "size": len(data) if record is None else record.size,
            })
        return normalized, None

    @staticmethod
    def _has_stored_attachment(value: object) -> bool:
        return isinstance(value, list) and any(isinstance(item, dict) and (item.get("file_id") or item.get("id")) for item in value)

    async def _handle_message(self, request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)
        content = body.get("content", "")
        if not isinstance(content, str):
            return JSONResponse({"error": "'content' must be a string"}, status_code=400)
        if self._has_stored_attachment(body.get("attachments")) and not self.file_upload_allowed:
            return self._file_upload_blocked()
        attachments, attachment_error = await self._normalize_attachments(body.get("attachments"))
        if attachment_error is not None:
            return JSONResponse({"error": attachment_error}, status_code=400)
        if not content.strip() and not attachments:
            return JSONResponse({"error": "Message must contain text or at least one attachment"}, status_code=400)
        previous_item_id = body.get("previous_item_id")
        if previous_item_id is not None and (isinstance(previous_item_id, bool) or not isinstance(previous_item_id, int)):
            return JSONResponse({"error": "'previous_item_id' must be an integer or null"}, status_code=400)
        user = request.state.user
        if not await self._validate_parent(user.id, previous_item_id):
            return JSONResponse({"error": "The selected branch is not available"}, status_code=403)
        stream_requested = request.query_params.get("stream") == "1"
        payload = {
            "platform": "http",
            "user_id": user.id,
            "username": user.username,
            "content": content,
            "attachments": attachments,
            "previous_item_id": previous_item_id,
            "timezone": body.get("timezone"),
        }
        known_ids: set[int] = set()
        if not stream_requested:
            before = await self._user_history(user.id)
            known_ids = {item.item_id for item in before if item.item_id is not None}

        async def _run_agent() -> None:
            token = self._request_streaming.set(stream_requested)
            try:
                tasks = await self.agent.handle(payload)
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
                self.logger.exception("HTTP non-stream request failed user_id=%d", user.id)
                return JSONResponse({"error": str(exc)}, status_code=500)
            after = await self._user_history(user.id)
            items = [item for item in after if item.item_id not in known_ids]
            return JSONResponse({"items": [_serialize_item(item) for item in items]})

        stream_id = uuid.uuid4().hex

        async def _run_wrapper() -> None:
            try:
                await _run_agent()
            except asyncio.CancelledError:
                pass
            except Exception as stream_error:
                self.logger.exception("HTTP background stream failed stream_id=%s", stream_id)
                await self._publish(user.id, {"type": "error", "error": str(stream_error), "stream_id": stream_id})
            finally:
                await self._publish(user.id, {"type": "message_done", "stream_id": stream_id})
                self._stream_tasks.pop(stream_id, None)
                self._stream_users.pop(stream_id, None)

        wrapper_task = asyncio.create_task(_run_wrapper(), name=f"http-stream:{stream_id}")
        self._stream_tasks[stream_id] = wrapper_task
        self._stream_users[stream_id] = user.id
        self.logger.info("HTTP message stream started user_id=%d", user.id)
        return JSONResponse({"stream_id": stream_id}, status_code=202)

    async def _handle_events(self, request: Request) -> Response:
        session = self._open_session(request.state.user.id)
        self.logger.info("HTTP event stream opened user_id=%d", request.state.user.id)
        return EventSourceResponse(
            _sse_generator(session.queue, lambda: self._close_session(session)),
            ping=15,
            sep="\n",
            ping_message_factory=lambda: ServerSentEvent(comment="ping", sep="\n"),
            send_timeout=30,
            headers={"Cache-Control": "no-cache"},
        )

    async def _handle_history(self, request: Request) -> Response:
        user_id = request.state.user.id
        items = await self._history_for_user(user_id)
        heads = self._history_heads(items, user_id)
        branch_head_value = request.query_params.get("branch_head")
        current_head_id: int | None = None
        if branch_head_value == "latest":
            if heads:
                current_head_id = heads[0][0].item_id
        elif branch_head_value:
            try:
                current_head_id = int(branch_head_value)
            except ValueError:
                return JSONResponse({"error": "'branch_head' must be an integer, 'latest', or null"}, status_code=400)
            if current_head_id not in {item.item_id for item in items}:
                current_head_id = None

        head_payloads = []
        if request.query_params.get("heads") == "1":
            for head, root in heads:
                payload = _serialize_item(head)
                payload["branch_head_id"] = head.item_id
                payload["branch_root_id"] = root.item_id
                payload["branch_preview"] = self._branch_preview(items, root, user_id)
                payload["branch_updated_at"] = head.created_at.isoformat() if head.created_at else None
                head_payloads.append(payload)

        branch_items = self._history_tree(items, current_head_id)
        return JSONResponse({
            "items": [self._serialize_history_item(item, user_id) for item in branch_items],
            "heads": head_payloads,
            "current_head_id": current_head_id,
        })


async def _sse_generator(queue: asyncio.Queue[dict | None], on_disconnect=None):
    try:
        yield JSONServerSentEvent({"type": "ready"})
        while True:
            item = await queue.get()
            if item is None:
                break
            yield JSONServerSentEvent(item)
    finally:
        if on_disconnect is not None:
            on_disconnect()
    yield JSONServerSentEvent({"type": "done"})


def _serialize_item(item: DialogItem) -> dict:
    meta = {key: value for key, value in item.meta.items() if key != "llm"}
    return {"type": "dialog_item", "item_id": item.item_id, "previous_item_id": item.previous_item_id, "item_type": item.item_type.value, "role": item.role.value, "content": item.content, "user": item.user, "origin": item.origin.model_dump(mode="json"), "external_id": item.external_id, "created_at": item.created_at.isoformat() if item.created_at else None, "meta": meta}
