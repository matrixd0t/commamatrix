# tests/test_connector.py

"""Tests for Connector, ConnectorDescriptor, ConnectorManager, PythonConnectorSource."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from commamatrix.components.connector import (
    CONNECTOR_ATTRIBUTE,
    Connector,
    ConnectorDescriptor,
    ConnectorManager,
    PythonConnectorSource,
)
from commamatrix.components.dialog import (
    DialogItem,
    DialogItemType,
    DialogOrigin,
    DialogRole,
)
from commamatrix.components.hook import OnParsedCtx
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from tests.conftest import StubOrigin, stub_agent, stub_origin


class TestConnectorSubclass:
    def test_stamps_connector_attribute(self):
        class MyConn(Connector[StubOrigin]):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""
        assert getattr(MyConn, CONNECTOR_ATTRIBUTE, False) is True

    def test_origin_types(self):
        class MyConn(Connector[StubOrigin]):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""
        assert MyConn.origin_types == (StubOrigin,)

    def test_connector_has_parse_and_send(self):
        class MyConn(Connector[StubOrigin]):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""
        import asyncio
        agent = stub_agent()
        conn = MyConn(agent=agent)
        assert asyncio.iscoroutinefunction(conn.parse)
        assert asyncio.iscoroutinefunction(conn.send)


class TestPythonConnectorSource:
    def test_scan_finds_connector(self):
        class TestConn(Connector[StubOrigin]):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""

        mod = types.ModuleType("conn_test_mod")
        mod.TestConn = TestConn
        TestConn.__module__ = "conn_test_mod"
        sys.modules["conn_test_mod"] = mod
        try:
            src = PythonConnectorSource()
            src.set_scope(["conn_test_mod"])
            descriptors = src.scan()
            assert len(descriptors) == 1
            assert descriptors[0].connector_cls is TestConn
        finally:
            del sys.modules["conn_test_mod"]


class TestConnectorManager:
    @pytest.mark.asyncio
    async def test_creates_connector_instance(self):
        class TestConn2(Connector[StubOrigin]):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""

        mod = types.ModuleType("cm_test_mod")
        mod.TestConn2 = TestConn2
        TestConn2.__module__ = "cm_test_mod"
        sys.modules["cm_test_mod"] = mod
        try:
            agent = stub_agent()
            mgr = ConnectorManager(agent=agent)
            mgr.set_scope(["cm_test_mod"])
            await mgr.start()
            connectors = mgr.resolve()
            assert len(connectors) == 1
            assert isinstance(connectors[0], TestConn2)
            await mgr.stop()
        finally:
            del sys.modules["cm_test_mod"]


class TestConnectorLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_listener_task(self):
        class SimpleConn(Connector[StubOrigin]):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""

        agent = stub_agent()
        conn = SimpleConn(agent=agent)
        await conn.start()
        assert conn.listener_task is not None
        await conn.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        class SimpleConn2(Connector[StubOrigin]):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""

        agent = stub_agent()
        conn = SimpleConn2(agent=agent)
        await conn.start()
        task = conn.listener_task
        await conn.stop()
        assert task.done()
        assert conn.listener_task is None
