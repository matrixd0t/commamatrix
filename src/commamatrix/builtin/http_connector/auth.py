# builtin/http_connector/auth.py

from __future__ import annotations

import asyncio
import logging
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


@dataclass(frozen=True, slots=True)
class InitialAdminCredentials:
    username: str
    password: str


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
_USERNAME_MIN_LENGTH = 2
_USERNAME_MAX_LENGTH = 32
_USERNAME_SEPARATORS = frozenset(" ._-'")


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
        self.logger = getattr(agent, "logger", logging.getLogger(__name__))
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

    @staticmethod
    def _normalize_username(username: str) -> str:
        if not isinstance(username, str):
            raise AuthError("Username is required")
        return " ".join(unicodedata.normalize("NFC", username).strip().split())

    @staticmethod
    def _validate_username(username: str) -> str:
        username = Authorizer._normalize_username(username)
        if not _USERNAME_MIN_LENGTH <= len(username) <= _USERNAME_MAX_LENGTH:
            raise AuthError(f"Username must be between {_USERNAME_MIN_LENGTH} and {_USERNAME_MAX_LENGTH} characters")
        if not any(unicodedata.category(char).startswith("L") for char in username):
            raise AuthError("Username must contain at least one letter")
        first_category = unicodedata.category(username[0])
        last_category = unicodedata.category(username[-1])
        if not (first_category.startswith("L") or first_category == "Nd") or not (last_category.startswith("L") or last_category == "Nd"):
            raise AuthError("Username must start and end with a letter or number")
        for char in username:
            category = unicodedata.category(char)
            if not (category.startswith(("L", "M")) or category == "Nd" or char in _USERNAME_SEPARATORS):
                raise AuthError("Username contains unsupported characters")
        return username

    def _user_from_row(self, row, username: str | None = None) -> AuthUser:
        return AuthUser(
            id=int(row["id"]),
            username=username if username is not None else row["username"],
            app_name=self.app_name,
            is_admin=bool(row["is_admin"]),
        )

    async def init_db(self) -> InitialAdminCredentials | None:
        async with self._init_lock:
            if self._initialized:
                return None
            self.logger.info("HTTP auth database initializing app=%s", self.app_name)
            await self.agent.storage.execute(
                f"CREATE TABLE IF NOT EXISTS {_AUTH_TABLE} ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "app_name TEXT NOT NULL, "
                "username TEXT NOT NULL, "
                "password_hash TEXT NOT NULL, "
                "is_admin INTEGER NOT NULL, "
                "created_at TEXT NOT NULL, "
                "UNIQUE (app_name, username)"
                ")"
            )
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
                self.logger.info("HTTP administrator account created app=%s", self.app_name)
                credentials = InitialAdminCredentials(username="admin", password=password)
            else:
                credentials = None
            self._initialized = True
            self.logger.info("HTTP auth database ready app=%s", self.app_name)
            return credentials

    async def _ensure_username_available(self, username: str, exclude_user_id: int | None = None) -> None:
        rows = await self.agent.storage.execute(f"SELECT id, username FROM {_AUTH_TABLE} WHERE app_name = ?", (self.app_name,))
        if any(int(row["id"]) != exclude_user_id and self._normalize_username(str(row["username"])) == username for row in rows):
            raise AuthError("Username already taken for this app")

    async def _insert_user(self, username: str, password: str, is_admin: bool = False) -> AuthUser:
        username = self._validate_username(username)
        self._check_password(password)
        await self._ensure_username_available(username)
        password_hash = self._hash_password(password)
        try:
            await self.agent.storage.execute(
                f"INSERT INTO {_AUTH_TABLE} (app_name, username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
                (self.app_name, username, password_hash, int(is_admin), datetime.now(UTC).isoformat()),
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
    def _check_password(password: str) -> None:
        if not isinstance(password, str) or not password:
            raise AuthError("Password is required")
        if len(password.encode()) > 72:
            raise AuthError("Password is too long")

    async def register(self, username: str, password: str) -> AuthUser:
        await self.init_db()
        return await self._insert_user(username, password)

    async def create_invite(self) -> str:
        await self.init_db()
        token = secrets.token_urlsafe(32)
        self._invites.add(token)
        self.logger.info("HTTP invitation created app=%s active_invites=%d", self.app_name, len(self._invites))
        return token

    async def register_with_invite(self, token: str, username: str, password: str) -> AuthUser:
        await self.init_db()
        if not isinstance(token, str) or token not in self._invites:
            self.logger.warning("HTTP invitation rejected app=%s", self.app_name)
            raise AuthError("Invalid or expired invitation")
        username = self._validate_username(username)
        self._check_password(password)
        await self._ensure_username_available(username)
        self._invites.remove(token)
        return await self._insert_user(username, password)

    async def login(self, username: str, password: str) -> str:
        await self.init_db()
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthError("Invalid username or password")
        rows = await self.agent.storage.execute(
            f"SELECT id, username, password_hash FROM {_AUTH_TABLE} WHERE app_name = ?",
            (self.app_name,),
        )
        username_value = self._normalize_username(username)
        row = next((candidate for candidate in rows if self._normalize_username(str(candidate["username"])) == username_value), None)
        if row is None:
            self.logger.warning("HTTP login failed app=%s reason=unknown_user", self.app_name)
            raise AuthError("Invalid username or password")
        if not self._password_matches(password, row["password_hash"]):
            self.logger.warning("HTTP login failed app=%s reason=invalid_password", self.app_name)
            raise AuthError("Invalid username or password")
        user_id = int(row["id"])
        token = self._issue_token(user_id, row["username"])
        self.logger.info("HTTP login succeeded app=%s user_id=%d", self.app_name, user_id)
        return token

    def _issue_token(self, user_id: int, username: str) -> str:
        now = datetime.now(UTC)
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
            user = self._normalize_username(user)
            try:
                user_id = int(user)
            except ValueError:
                rows = await self.agent.storage.execute(
                    f"SELECT id, username, is_admin FROM {_AUTH_TABLE} WHERE app_name = ?",
                    (self.app_name,),
                )
                rows = [row for row in rows if self._normalize_username(str(row["username"])) == user]
            else:
                rows = await self.agent.storage.execute(
                    f"SELECT id, username, is_admin FROM {_AUTH_TABLE} WHERE id = ? AND app_name = ?",
                    (user_id, self.app_name),
                )
        return self._user_from_row(rows[0]) if rows else None

    async def change_password(self, user: AuthUser, old_password: str, new_password: str) -> None:
        await self.init_db()
        self._check_password(old_password)
        self._check_password(new_password)
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

    async def change_username(self, user: AuthUser, username: str) -> AuthUser:
        await self.init_db()
        username = self._validate_username(username)
        await self._ensure_username_available(username, exclude_user_id=user.id)
        try:
            await self.agent.storage.execute(
                f"UPDATE {_AUTH_TABLE} SET username = ? WHERE id = ? AND app_name = ?",
                (username, user.id, self.app_name),
            )
        except Exception as exc:
            if "unique" in str(exc).lower() or "constraint" in str(exc).lower():
                raise AuthError("Username already taken for this app") from exc
            raise
        return AuthUser(id=user.id, username=username, app_name=self.app_name, is_admin=user.is_admin)

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
            self.logger.warning("HTTP authentication failed app=%s reason=%s", self.app_name, type(exc).__name__)
            return JSONResponse({"detail": str(exc)}, status_code=401)
        except Exception:
            self.logger.exception("HTTP authentication backend failed app=%s", self.app_name)
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






