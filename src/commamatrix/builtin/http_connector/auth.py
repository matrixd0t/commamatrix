# builtin/http_connector/auth.py

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import TYPE_CHECKING

import bcrypt
import jwt
from pydantic import BaseModel
from starlette.responses import JSONResponse

from ...components.table import BaseTable

if TYPE_CHECKING:
    from ...core.agent import Agent


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: int
    username: str
    app_name: str
    is_admin: bool


class UserName(BaseModel):
    user: str
    name: str
    alternatives: list[str]


class UserNamesTable(BaseTable[UserName]):
    table_id = "commamatrix.http_user_names"
    table_name = "commamatrix_user_names"
    row_model = UserName
    primary_key = "user"
    indexes = (("name",),)


_AUTH_TABLE = "commamatrix_http_auth"


class HttpAuthRow(BaseModel):
    id: int
    app_name: str
    username: str
    password_hash: str
    is_admin: bool
    created_at: str


class HttpAuthTable(BaseTable[HttpAuthRow]):
    table_id = "commamatrix.http_auth"
    table_name = _AUTH_TABLE
    row_model = HttpAuthRow
    primary_key = "id"
    auto_increment = "id"
    unique_indexes = (("app_name", "username"),)


class AuthError(Exception):
    """Authentication and authorization failure."""


class Authorizer:
    def __init__(self, agent: Agent, app_name: str, jwt_secret: str, token_ttl_seconds: int) -> None:
        if not jwt_secret:
            raise ValueError("JWT secret must not be empty")
        if token_ttl_seconds <= 0:
            raise ValueError("JWT token TTL must be positive")
        self.agent = agent
        self.app_name = app_name
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = "HS256"
        self.token_ttl_seconds = token_ttl_seconds
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._invites: set[str] = set()

    @staticmethod
    def _hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def _password_matches(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except (ValueError, TypeError):
            return False

    def _user_from_row(self, row, username: str | None = None) -> AuthUser:
        return AuthUser(
            id=int(row["id"]),
            username=username if username is not None else row["username"],
            app_name=self.app_name,
            is_admin=bool(row["is_admin"]),
        )

    async def init_db(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            admins = await self.agent.storage.execute(
                f"SELECT id FROM {_AUTH_TABLE} WHERE app_name = ? AND is_admin = 1 LIMIT 1",
                (self.app_name,),
            )
            if not admins:
                password = secrets.token_urlsafe(18)
                password_hash = self._hash_password(password)
                existing_admin = await self.agent.storage.execute(
                    f"SELECT id FROM {_AUTH_TABLE} WHERE app_name = ? AND username = ? LIMIT 1",
                    (self.app_name, "admin"),
                )
                if existing_admin:
                    await self.agent.storage.execute(
                        f"UPDATE {_AUTH_TABLE} SET password_hash = ?, is_admin = 1 WHERE id = ? AND app_name = ?",
                        (password_hash, existing_admin[0]["id"], self.app_name),
                    )
                else:
                    await self._insert_user("admin", password, is_admin=True)
                print("Admin account created. Save this password; you won't be able to see it again: " + password)
            self._initialized = True

    async def _insert_user(self, username: str, password: str, is_admin: bool = False) -> AuthUser:
        password_hash = self._hash_password(password)
        try:
            await self.agent.storage.execute(
                f"INSERT INTO {_AUTH_TABLE} (app_name, username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
                (self.app_name, username, password_hash, int(is_admin), datetime.now(timezone.utc).isoformat()),
            )
        except Exception as exc:
            if "unique" in str(exc).lower() or "constraint" in str(exc).lower():
                raise AuthError("Username already taken for this app") from exc
            raise
        rows = await self.agent.storage.execute(
            f"SELECT id, is_admin FROM {_AUTH_TABLE} WHERE app_name = ? AND username = ?",
            (self.app_name, username),
        )
        return self._user_from_row(rows[0], username)

    @staticmethod
    def _check_credentials(username: str, password: str) -> None:
        if not isinstance(username, str) or not username.strip():
            raise AuthError("Username is required")
        if not isinstance(password, str) or not password:
            raise AuthError("Password is required")
        if len(password.encode()) > 72:
            raise AuthError("Password is too long")

    async def register(self, username: str, password: str) -> AuthUser:
        await self.init_db()
        username = username.strip() if isinstance(username, str) else username
        self._check_credentials(username, password)
        return await self._insert_user(username, password)

    async def create_invite(self) -> str:
        await self.init_db()
        token = secrets.token_urlsafe(32)
        self._invites.add(token)
        return token

    async def register_with_invite(self, token: str, username: str, password: str) -> AuthUser:
        await self.init_db()
        if not isinstance(token, str) or token not in self._invites:
            raise AuthError("Invalid or expired invitation")
        self._invites.remove(token)
        username = username.strip() if isinstance(username, str) else username
        self._check_credentials(username, password)
        return await self._insert_user(username, password)

    async def login(self, username: str, password: str) -> str:
        await self.init_db()
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthError("Invalid username or password")
        rows = await self.agent.storage.execute(
            f"SELECT id, password_hash FROM {_AUTH_TABLE} WHERE app_name = ? AND username = ?",
            (self.app_name, username),
        )
        if not rows:
            raise AuthError("Invalid username or password")
        row = rows[0]
        if not self._password_matches(password, row["password_hash"]):
            raise AuthError("Invalid username or password")
        return self._issue_token(int(row["id"]), username)

    def _issue_token(self, user_id: int, username: str) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": str(user_id),
                "username": username,
                "app": self.app_name,
                "iat": now,
                "exp": now + timedelta(seconds=self.token_ttl_seconds),
            },
            self.jwt_secret,
            algorithm=self.jwt_algorithm,
        )

    def _decode_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("Token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid token") from exc
        if payload.get("app") != self.app_name:
            raise AuthError("Token is not valid for this app")
        return payload

    async def authenticate(self, token: str) -> AuthUser:
        await self.init_db()
        payload = self._decode_token(token)
        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthError("Invalid token") from exc
        rows = await self.agent.storage.execute(
            f"SELECT id, username, is_admin FROM {_AUTH_TABLE} WHERE id = ? AND app_name = ?",
            (user_id, self.app_name),
        )
        if not rows:
            raise AuthError("User no longer exists")
        return self._user_from_row(rows[0])

    async def find_user(self, user: int | str) -> AuthUser | None:
        await self.init_db()
        if isinstance(user, bool) or not isinstance(user, (int, str)):
            raise ValueError("User must be an integer ID or username")
        if isinstance(user, int):
            rows = await self.agent.storage.execute(
                f"SELECT id, username, is_admin FROM {_AUTH_TABLE} WHERE id = ? AND app_name = ?",
                (user, self.app_name),
            )
        else:
            user = user.strip()
            try:
                user_id = int(user)
            except ValueError:
                rows = await self.agent.storage.execute(
                    f"SELECT id, username, is_admin FROM {_AUTH_TABLE} WHERE LOWER(username) = LOWER(?) AND app_name = ?",
                    (user, self.app_name),
                )
            else:
                rows = await self.agent.storage.execute(
                    f"SELECT id, username, is_admin FROM {_AUTH_TABLE} WHERE id = ? AND app_name = ?",
                    (user_id, self.app_name),
                )
        return self._user_from_row(rows[0]) if rows else None

    async def change_password(self, user: AuthUser, old_password: str, new_password: str) -> None:
        await self.init_db()
        self._check_credentials(user.username, old_password)
        self._check_credentials(user.username, new_password)
        rows = await self.agent.storage.execute(
            f"SELECT password_hash FROM {_AUTH_TABLE} WHERE id = ? AND app_name = ?",
            (user.id, self.app_name),
        )
        if not rows:
            raise AuthError("User no longer exists")
        if not self._password_matches(old_password, rows[0]["password_hash"]):
            raise AuthError("Invalid current password")
        password_hash = self._hash_password(new_password)
        await self.agent.storage.execute(
            f"UPDATE {_AUTH_TABLE} SET password_hash = ? WHERE id = ? AND app_name = ?",
            (password_hash, user.id, self.app_name),
        )

    @staticmethod
    def extract_bearer_token(header: str | None) -> str:
        if not header or not header.startswith("Bearer "):
            raise AuthError("Missing or malformed Authorization header")
        token = header.removeprefix("Bearer ").strip()
        if not token:
            raise AuthError("Missing or malformed Authorization header")
        return token

    async def _authenticate_request(self, request):
        try:
            token = self.extract_bearer_token(request.headers.get("Authorization"))
            request.state.user = await self.authenticate(token)
        except AuthError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)
        except Exception:
            return JSONResponse({"detail": "Authentication service unavailable"}, status_code=503)
        return None

    def _protect(self, endpoint, admin: bool = False):
        @wraps(endpoint)
        async def wrapper(request, *args, **kwargs):
            response = await self._authenticate_request(request)
            if response is not None:
                return response
            if admin and not request.state.user.is_admin:
                return JSONResponse({"detail": "Administrator access required"}, status_code=403)
            return await endpoint(request, *args, **kwargs)

        return wrapper

    def requires_auth(self, endpoint):
        return self._protect(endpoint)

    def requires_admin(self, endpoint):
        return self._protect(endpoint, admin=True)

    async def stop(self) -> None:
        self._invites.clear()


