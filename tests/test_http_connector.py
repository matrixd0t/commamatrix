# tests/test_http_connector.py

"""Tests for HttpConnector, HttpOrigin, and HTTP routes."""

from __future__ import annotations

import asyncio
import sys
import types

import httpx
import pytest

from commamatrix.components.connector import CONNECTOR_ATTRIBUTE
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.hook import OnParsedCtx
from commamatrix.builtin.http_connector.connector import HttpConnector, HttpRequestContext
from commamatrix.builtin.http_connector.context import HttpOrigin
from tests.conftest import stub_agent


def _make_connector(agent=None) -> HttpConnector:
    if agent is None:
        agent = stub_agent()
    return HttpConnector(agent=agent)


def _mock_agent(handle_fn) -> object:
    from commamatrix.components.config import Config

    class _Agent:
        config = Config()

        async def handle(self_inner, payload):
            return await handle_fn(payload)

    return _Agent()


class TestHttpOrigin:
    def test_platform(self):
        origin = HttpOrigin(session_id="s1")
        assert origin.platform == "http"

    def test_session_id(self):
        origin = HttpOrigin(session_id="abc")
        assert origin.session_id == "abc"

    def test_serialization(self):
        origin = HttpOrigin(session_id="s1")
        data = origin.model_dump(mode="json")
        assert data == {"platform": "http", "session_id": "s1"}

    def test_registered_in_origin_registry(self):
        from commamatrix.components.dialog import ORIGIN_REGISTRY
        assert "HttpOrigin" in ORIGIN_REGISTRY


class TestHttpConnectorAttribute:
    def test_stamps_connector_attribute(self):
        assert getattr(HttpConnector, CONNECTOR_ATTRIBUTE, False) is True

    def test_origin_types(self):
        assert HttpConnector.origin_types == (HttpOrigin,)


class TestHttpConnectorParse:
    @pytest.mark.asyncio
    async def test_ignores_non_http_payload(self):
        conn = _make_connector()
        result = await conn.parse({"platform": "cli", "content": "hi"})
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_correct_origin(self):
        conn = _make_connector()
        result = await conn.parse({
            "platform": "http",
            "session_id": "s1",
            "content": "hello",
        })
        assert result is not None
        assert len(result.dialog_items) == 1
        origin = result.dialog_items[0].origin
        assert isinstance(origin, HttpOrigin)
        assert origin.session_id == "s1"

    @pytest.mark.asyncio
    async def test_creates_correct_dialog_item(self):
        conn = _make_connector()
        result = await conn.parse({
            "platform": "http",
            "session_id": "s1",
            "username": "alice",
            "content": "test message",
        })
        item = result.dialog_items[0]
        assert item.content == "test message"
        assert item.item_type == DialogItemType.INPUT
        assert item.role == DialogRole.USER
        assert item.user == "http:alice"

    @pytest.mark.asyncio
    async def test_default_username(self):
        conn = _make_connector()
        result = await conn.parse({
            "platform": "http",
            "session_id": "s1",
            "content": "hi",
        })
        assert result.dialog_items[0].user == "http:web"

    @pytest.mark.asyncio
    async def test_previous_external_id(self):
        conn = _make_connector()
        result = await conn.parse({
            "platform": "http",
            "session_id": "s1",
            "content": "hi",
            "previous_external_id": "http:s1:5",
        })
        assert result.previous_external_id == "http:s1:5"

    @pytest.mark.asyncio
    async def test_previous_external_id_none(self):
        conn = _make_connector()
        result = await conn.parse({
            "platform": "http",
            "session_id": "s1",
            "content": "hi",
        })
        assert result.previous_external_id is None


class TestHttpConnectorSend:
    @pytest.mark.asyncio
    async def test_returns_empty_for_non_http_origin(self):
        from tests.conftest import StubOrigin
        conn = _make_connector()
        item = DialogItem(
            content="hi",
            item_type=DialogItemType.OUTPUT,
            role=DialogRole.ASSISTANT,
            origin=StubOrigin(),
        )
        assert await conn.send(StubOrigin(), item) == ""

    @pytest.mark.asyncio
    async def test_returns_empty_without_active_request(self):
        conn = _make_connector()
        origin = HttpOrigin(session_id="s1")
        item = DialogItem(
            content="hi",
            item_type=DialogItemType.OUTPUT,
            role=DialogRole.ASSISTANT,
            origin=origin,
        )
        assert await conn.send(origin, item) == ""

    @pytest.mark.asyncio
    async def test_accumulates_items(self):
        conn = _make_connector()
        origin = HttpOrigin(session_id="s1")
        conn._active_requests["s1"] = HttpRequestContext(
            request_id="r1", session_id="s1", username="web",
        )

        item1 = DialogItem(content="a", item_type=DialogItemType.OUTPUT, role=DialogRole.ASSISTANT, origin=origin)
        item2 = DialogItem(content="b", item_type=DialogItemType.OUTPUT, role=DialogRole.ASSISTANT, origin=origin)

        await conn.send(origin, item1)
        await conn.send(origin, item2)

        assert len(conn._active_requests["s1"].items) == 2

    @pytest.mark.asyncio
    async def test_returns_unique_external_ids(self):
        conn = _make_connector()
        origin = HttpOrigin(session_id="s1")
        conn._active_requests["s1"] = HttpRequestContext(
            request_id="r1", session_id="s1", username="web",
        )

        item = DialogItem(content="a", item_type=DialogItemType.OUTPUT, role=DialogRole.ASSISTANT, origin=origin)
        id1 = await conn.send(origin, item)
        id2 = await conn.send(origin, item)

        assert id1 != id2
        assert id1.startswith("http:s1:")
        assert id2.startswith("http:s1:")

    @pytest.mark.asyncio
    async def test_updates_last_external_id(self):
        conn = _make_connector()
        origin = HttpOrigin(session_id="s1")
        ctx = HttpRequestContext(request_id="r1", session_id="s1", username="web")
        conn._active_requests["s1"] = ctx

        item = DialogItem(content="a", item_type=DialogItemType.OUTPUT, role=DialogRole.ASSISTANT, origin=origin)
        ext_id = await conn.send(origin, item)

        assert ctx.last_external_id == ext_id


class TestHttpConnectorRoutes:
    @pytest.mark.asyncio
    async def test_health(self):
        conn = _make_connector()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_index_returns_html(self):
        conn = _make_connector()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_message_invalid_json(self):
        conn = _make_connector()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/message",
                content="not json",
                headers={"content-type": "application/json"},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_message_missing_content(self):
        conn = _make_connector()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", json={"session_id": "s1"})
            assert resp.status_code == 400
            assert "content" in resp.json()["error"].lower()

    @pytest.mark.asyncio
    async def test_message_empty_content(self):
        conn = _make_connector()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", json={"content": "  "})
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_message_body_not_object(self):
        conn = _make_connector()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", content='"string"', headers={"content-type": "application/json"})
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_message_waits_for_run_completion(self):
        send_called = asyncio.Event()
        connector_ref = None

        async def mock_handle(payload):
            nonlocal connector_ref
            session_id = payload["session_id"]
            origin = HttpOrigin(session_id=session_id)
            parsed = await connector_ref.parse(payload)
            connector = parsed.connector

            async def mock_run():
                item = DialogItem(
                    content="response",
                    item_type=DialogItemType.OUTPUT,
                    role=DialogRole.ASSISTANT,
                    origin=origin,
                )
                await connector.send(origin, item)
                send_called.set()

            return [asyncio.create_task(mock_run())]

        agent = _mock_agent(mock_handle)
        conn = _make_connector(agent=agent)
        connector_ref = conn

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", json={
                "session_id": "s1",
                "content": "hello",
            })
            assert resp.status_code == 200
            assert send_called.is_set()
            data = resp.json()
            assert data["session_id"] == "s1"
            assert len(data["items"]) == 1
            assert data["items"][0]["content"] == "response"

    @pytest.mark.asyncio
    async def test_message_returns_multiple_items(self):
        connector_ref = None

        async def mock_handle(payload):
            nonlocal connector_ref
            session_id = payload["session_id"]
            origin = HttpOrigin(session_id=session_id)
            parsed = await connector_ref.parse(payload)
            connector = parsed.connector

            async def mock_run():
                for content in ["block1", "block2", "block3"]:
                    item = DialogItem(
                        content=content,
                        item_type=DialogItemType.OUTPUT,
                        role=DialogRole.ASSISTANT,
                        origin=origin,
                    )
                    await connector.send(origin, item)

            return [asyncio.create_task(mock_run())]

        agent = _mock_agent(mock_handle)
        conn = _make_connector(agent=agent)
        connector_ref = conn

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", json={
                "session_id": "s1",
                "content": "hello",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 3
            assert [i["content"] for i in data["items"]] == ["block1", "block2", "block3"]

    @pytest.mark.asyncio
    async def test_message_agent_error_returns_500(self):
        async def failing_handle(payload):
            async def fail():
                raise RuntimeError("LLM failed")
            return [asyncio.create_task(fail())]

        conn = _make_connector(agent=_mock_agent(failing_handle))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", json={
                "session_id": "s1",
                "content": "hello",
            })
            assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_message_generates_session_id(self):
        async def silent_handle(payload):
            return [asyncio.create_task(asyncio.sleep(0))]

        conn = _make_connector(agent=_mock_agent(silent_handle))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", json={"content": "hi"})
            assert resp.status_code == 200
            data = resp.json()
            assert "session_id" in data
            assert len(data["session_id"]) > 0

    @pytest.mark.asyncio
    async def test_message_cleans_up_context(self):
        connector_ref = None

        async def mock_handle(payload):
            nonlocal connector_ref
            session_id = payload["session_id"]
            origin = HttpOrigin(session_id=session_id)
            parsed = await connector_ref.parse(payload)
            connector = parsed.connector

            async def mock_run():
                item = DialogItem(
                    content="ok",
                    item_type=DialogItemType.OUTPUT,
                    role=DialogRole.ASSISTANT,
                    origin=origin,
                )
                await connector.send(origin, item)

            return [asyncio.create_task(mock_run())]

        agent = _mock_agent(mock_handle)
        conn = _make_connector(agent=agent)
        connector_ref = conn

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/message", json={
                "session_id": "s1",
                "content": "hello",
            })
            assert resp.status_code == 200
            assert "s1" not in conn._active_requests

    @pytest.mark.asyncio
    async def test_different_sessions_parallel(self):
        events: dict[str, asyncio.Event] = {
            "s1": asyncio.Event(),
            "s2": asyncio.Event(),
        }
        order: list[str] = []
        connector_ref = None

        async def mock_handle(payload):
            nonlocal connector_ref
            sid = payload["session_id"]
            origin = HttpOrigin(session_id=sid)
            parsed = await connector_ref.parse(payload)
            connector = parsed.connector

            async def mock_run():
                order.append(f"start:{sid}")
                await events[sid].wait()
                item = DialogItem(
                    content=f"done:{sid}",
                    item_type=DialogItemType.OUTPUT,
                    role=DialogRole.ASSISTANT,
                    origin=origin,
                )
                await connector.send(origin, item)
                order.append(f"end:{sid}")

            return [asyncio.create_task(mock_run())]

        agent = _mock_agent(mock_handle)
        conn = _make_connector(agent=agent)
        connector_ref = conn

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            t1 = asyncio.create_task(client.post("/api/message", json={"session_id": "s1", "content": "a"}))
            t2 = asyncio.create_task(client.post("/api/message", json={"session_id": "s2", "content": "b"}))

            await asyncio.sleep(0.05)
            assert "start:s1" in order
            assert "start:s2" in order

            events["s1"].set()
            events["s2"].set()

            r1 = await t1
            r2 = await t2

            assert r1.status_code == 200
            assert r2.status_code == 200

    @pytest.mark.asyncio
    async def test_same_session_serialized(self):
        call_count = 0
        gate = asyncio.Event()
        connector_ref = None

        async def mock_handle(payload):
            nonlocal call_count, connector_ref
            call_count += 1
            sid = payload["session_id"]
            origin = HttpOrigin(session_id=sid)
            parsed = await connector_ref.parse(payload)
            connector = parsed.connector

            async def mock_run():
                if call_count == 1:
                    await gate.wait()
                item = DialogItem(
                    content=f"r{call_count}",
                    item_type=DialogItemType.OUTPUT,
                    role=DialogRole.ASSISTANT,
                    origin=origin,
                )
                await connector.send(origin, item)

            return [asyncio.create_task(mock_run())]

        agent = _mock_agent(mock_handle)
        conn = _make_connector(agent=agent)
        connector_ref = conn

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            t1 = asyncio.create_task(client.post("/api/message", json={"session_id": "s1", "content": "a"}))
            t2 = asyncio.create_task(client.post("/api/message", json={"session_id": "s1", "content": "b"}))

            await asyncio.sleep(0.05)
            assert call_count == 1

            gate.set()
            r1 = await t1
            await asyncio.sleep(0.05)
            r2 = await t2

            assert r1.status_code == 200
            assert r2.status_code == 200


class TestHttpConnectorLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        conn = _make_connector()
        conn._port = 0
        await conn.start()
        assert conn.bound_port is not None
        assert conn.bound_port > 0
        assert conn.listener_task is not None
        await conn.stop()
        assert conn.bound_port is None
        assert conn.listener_task is None

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        conn = _make_connector()
        conn._port = 0
        await conn.start()
        port1 = conn.bound_port
        await conn.start()
        assert conn.bound_port == port1
        await conn.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up_state(self):
        conn = _make_connector()
        conn._port = 0
        await conn.start()

        conn._active_requests["s1"] = HttpRequestContext(
            request_id="r1", session_id="s1", username="web",
        )
        conn._session_locks["s1"] = asyncio.Lock()

        await conn.stop()
        assert len(conn._active_requests) == 0
        assert len(conn._session_locks) == 0

    @pytest.mark.asyncio
    async def test_base_url_property(self):
        conn = _make_connector()
        conn._port = 0
        await conn.start()
        assert f":{conn.bound_port}" in conn.base_url
        assert conn.base_url.startswith("http://127.0.0.1:")
        await conn.stop()

    @pytest.mark.asyncio
    async def test_server_listens_on_loopback(self):
        conn = _make_connector()
        conn._port = 0
        await conn.start()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=conn.app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

        await conn.stop()

    @pytest.mark.asyncio
    async def test_port_zero_resolves(self):
        conn = _make_connector()
        conn._port = 0
        await conn.start()
        assert conn._port == 0
        assert conn.bound_port != 0
        await conn.stop()
