# tests/test_http_connector.py

"""Tests for the authenticated HTTP connector and event transport."""

from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite
import httpx
import pytest

from commamatrix.builtin.http_connector.connector import HttpConnector, HttpOrigin
from commamatrix.components.config import Config
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.server import Server
from tests.conftest import stub_agent


class _AuthStorage:
    """Provide the SQL methods required by Authorizer."""

    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        if self._db is None:
            self._db = await aiosqlite.connect(":memory:")
            self._db.row_factory = aiosqlite.Row
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        await self._db.commit()
        return [dict(row) for row in rows]

    async def get_history(self, *, origin_type=None, origin_fields=None) -> list[DialogItem]:
        return []


class _HistoryStorage(_AuthStorage):
    """Record history filters and return configured items."""

    def __init__(self, items: list[DialogItem] | None = None) -> None:
        super().__init__()
        self.items = items or []
        self.last_origin_type = None
        self.last_origin_fields = None

    async def get_history(self, *, origin_type=None, origin_fields=None) -> list[DialogItem]:
        self.last_origin_type = origin_type
        self.last_origin_fields = origin_fields
        return self.items


async def _auth(conn: HttpConnector, username: str = "test-user") -> tuple[dict[str, str], int]:
    await conn.authorizer.init_db()
    user = await conn.authorizer.register(username, "test-password")
    token = await conn.authorizer.login(username, "test-password")
    return {"Authorization": f"Bearer {token}"}, user.id


def _make_connector(agent=None) -> HttpConnector:
    if agent is None:
        agent = stub_agent()
    if not hasattr(agent, "storage"):
        agent.storage = _AuthStorage()
    return HttpConnector(agent=agent)


def _mock_agent(handle_fn, storage=None) -> object:
    from commamatrix.components.config import Config

    class _Agent:
        config = Config()

        def __init__(self) -> None:
            self.storage = storage or _AuthStorage()

        async def handle(self_inner, payload):
            return await handle_fn(payload)

    return _Agent()


class TestHttpOrigin:
    def test_serialization(self):
        assert HttpOrigin(http_user_id=7).model_dump(mode="json") == {
            "origin_type": "http",
            "platform": "http",
            "http_user_id": 7,
        }

    def test_registered_in_origin_registry(self):
        from commamatrix.components.dialog import ORIGIN_REGISTRY

        assert "HttpOrigin" in ORIGIN_REGISTRY


class TestHttpConnectorParse:
    @pytest.mark.asyncio
    async def test_ignores_non_http_payload(self):
        assert await _make_connector().parse({"platform": "cli", "content": "hi"}) is None

    @pytest.mark.asyncio
    async def test_creates_user_origin_and_input_item(self):
        result = await _make_connector().parse({
            "platform": "http",
            "user_id": 7,
            "username": "alice",
            "content": "hello",
            "previous_item_id": 42,
        })

        assert result is not None
        item = result.dialog_items[0]
        assert item.content == "hello"
        assert item.item_type is DialogItemType.INPUT
        assert item.role is DialogRole.USER
        assert item.user == "http:7"
        assert item.origin == HttpOrigin(http_user_id=7)
        assert item.previous_item_id == 42


class TestHttpConnectorSend:
    @pytest.mark.asyncio
    async def test_returns_empty_for_non_http_origin(self):
        from tests.conftest import StubOrigin

        conn = _make_connector()
        item = DialogItem(content="hi", item_type=DialogItemType.OUTPUT, role=DialogRole.ASSISTANT, origin=StubOrigin())
        assert await conn.send(StubOrigin(), item) == ""

    @pytest.mark.asyncio
    async def test_returns_unique_user_scoped_external_ids(self):
        conn = _make_connector()
        origin = HttpOrigin(http_user_id=7)
        item = DialogItem(content="hi", item_type=DialogItemType.OUTPUT, role=DialogRole.ASSISTANT, origin=origin)

        first = await conn.send(origin, item)
        second = await conn.send(origin, item)

        assert first == ""
        assert second == ""


class TestHttpConnectorRoutes:
    @pytest.mark.asyncio
    async def test_health(self):
        conn = _make_connector()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=conn.app), base_url="http://test") as client:
            response = await client.get("/commamatrix/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_message_requires_authentication(self):
        conn = _make_connector()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=conn.app), base_url="http://test") as client:
            response = await client.post("/commamatrix/api/messages", json={"content": "hello"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_message_validates_json_and_content(self):
        conn = _make_connector()
        headers, _ = await _auth(conn)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=conn.app), base_url="http://test") as client:
            invalid_json = await client.post("/commamatrix/api/messages", content="not json", headers={**headers, "content-type": "application/json"})
            missing_content = await client.post("/commamatrix/api/messages", json={}, headers=headers)

        assert invalid_json.status_code == 400
        assert missing_content.status_code == 400
        assert "content" in missing_content.json()["error"].lower()

    @pytest.mark.asyncio
    async def test_message_passes_authenticated_user(self):
        received = {}

        async def handle(payload):
            received.update(payload)
            return []

        conn = _make_connector(_mock_agent(handle))
        headers, user_id = await _auth(conn)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=conn.app), base_url="http://test") as client:
            response = await client.post("/commamatrix/api/messages", json={"content": "hello"}, headers=headers)

        assert response.status_code == 200
        assert received["platform"] == "http"
        assert received["user_id"] == user_id
        assert received["content"] == "hello"
        assert received["previous_item_id"] is None

    @pytest.mark.asyncio
    async def test_history_is_filtered_by_authenticated_user(self):
        storage = _HistoryStorage()

        async def handle(_payload):
            return []

        conn = _make_connector(_mock_agent(handle, storage=storage))
        headers, user_id = await _auth(conn)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=conn.app), base_url="http://test") as client:
            response = await client.get("/commamatrix/api/history", headers=headers)

        assert response.status_code == 200
        assert response.json() == {"items": []}
        assert storage.last_origin_type is None
        assert storage.last_origin_fields is None

    @pytest.mark.asyncio
    async def test_background_error_is_published_to_user_events(self):
        conn = _make_connector()
        session = conn._open_session(7)

        async def fail():
            raise RuntimeError("LLM failed")

        task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        conn._log_task_error(7, task)
        event = await asyncio.wait_for(session.queue.get(), timeout=1)

        assert event == {"type": "error", "error": "LLM failed"}
        conn._close_session(session)


class TestHttpConnectorLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        conn = _make_connector()
        conn._port = 0
        await conn.start()
        assert conn._bound_port is not None and conn._bound_port > 0
        await conn.stop()
        assert conn._bound_port is None
        assert conn._server is None

    @pytest.mark.asyncio
    async def test_stop_closes_sessions(self):
        conn = _make_connector()
        session = conn._open_session(7)
        await conn.stop()
        assert session.closed
        assert conn._sessions == {}
        assert conn._sessions_by_user == {}


class TestHttpServerRoutes:
    @pytest.mark.asyncio
    async def test_routes_are_namespaced_under_commamatrix(self):
        class RouteAgent:
            def __init__(self) -> None:
                self.config = Config()
                self.storage = _AuthStorage()
                self.http_server = Server(self)

            async def handle(self, payload):
                return []

        agent = RouteAgent()
        HttpConnector(agent)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.http_server.app), base_url="http://test") as client:
            health = await client.get("/commamatrix/health")
            index = await client.get("/commamatrix/")
            script = await client.get("/commamatrix/ui/app.js")
            old_health = await client.get("/health")
            old_index = await client.get("/")

        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert index.status_code == 200
        assert '<base href="/commamatrix/ui/">' in index.text
        assert script.status_code == 200
        assert 'const SERVER_ROOT="/commamatrix"' in script.text
        assert old_health.status_code == 404
        assert old_index.status_code == 404
