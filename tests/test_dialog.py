# tests/test_dialog.py

"""Tests for dialog models: DialogItem, DialogOrigin, resolve_origin_type."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from commamatrix.components.dialog import (
    DEFAULT_PLATFORM,
    ORIGIN_REGISTRY,
    DialogItem,
    DialogItemType,
    DialogOrigin,
    DialogRole,
    resolve_origin_type,
)
from tests.conftest import StubOrigin, stub_origin


class TestDialogOrigin:
    def test_stub_origin_is_registered(self):
        assert "StubOrigin" in ORIGIN_REGISTRY

    def test_default_platform(self):
        origin = stub_origin()
        assert origin.platform == "test"

    def test_origin_is_frozen(self):
        origin = stub_origin()
        with pytest.raises(Exception):
            origin.chat_id = "other"

    def test_origin_equality(self):
        a = stub_origin("c1")
        b = stub_origin("c1")
        assert a == b

    def test_origin_inequality(self):
        a = stub_origin("c1")
        b = stub_origin("c2")
        assert a != b


class TestDialogItem:
    def test_basic_creation(self):
        item = DialogItem(
            content="hello",
            item_type=DialogItemType.INPUT,
            role=DialogRole.USER,
            origin=stub_origin(),
        )
        assert item.content == "hello"
        assert item.item_type == DialogItemType.INPUT
        assert item.role == DialogRole.USER
        assert item.item_id is None
        assert item.previous_item_id is None

    def test_defaults(self):
        item = DialogItem(
            content="x",
            item_type=DialogItemType.OUTPUT,
            role=DialogRole.ASSISTANT,
            origin=stub_origin(),
        )
        assert item.user == "unknown"
        assert item.external_id is None
        assert item.meta == {}

    def test_all_item_types(self):
        for it in DialogItemType:
            item = DialogItem(content="x", item_type=it, role=DialogRole.USER, origin=stub_origin())
            assert item.item_type == it

    def test_all_roles(self):
        for role in DialogRole:
            item = DialogItem(content="x", item_type=DialogItemType.INPUT, role=role, origin=stub_origin())
            assert item.role == role

    def test_meta_isolation(self):
        item1 = DialogItem(content="a", item_type=DialogItemType.INPUT, role=DialogRole.USER, origin=stub_origin())
        item2 = DialogItem(content="b", item_type=DialogItemType.INPUT, role=DialogRole.USER, origin=stub_origin())
        item1.meta["key"] = "val"
        assert "key" not in item2.meta


class TestResolveOriginType:
    def test_resolve_stub_origin(self):
        data = {"platform": "test", "chat_id": "abc"}
        cls = resolve_origin_type(data)
        assert cls is StubOrigin

    def test_resolve_default_origin(self):
        data = {"platform": "unknown"}
        cls = resolve_origin_type(data)
        assert cls is DialogOrigin

    def test_unknown_origin_raises(self):
        data = {"platform": "nonexistent_platform", "chat_id": "x"}
        with pytest.raises(ValueError, match="Unknown dialog origin"):
            resolve_origin_type(data)
