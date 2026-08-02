# tests/conftest.py

"""Shared fixtures for commamatrix tests."""

from __future__ import annotations

import sys
import types
import weakref
from dataclasses import dataclass
from typing import Any

import pytest

from commamatrix.core.classes.manager import ServiceInstanceRegistry
from commamatrix.core.classes.service import AbstractService
from commamatrix.components.config import Config, ConfigField
from commamatrix.components.dialog import DialogOrigin, DialogItem, DialogItemType, DialogRole
from commamatrix.components.hook import RunCtx
from commamatrix.components.tool import ToolDescriptor


class StubOrigin(DialogOrigin):
    platform: str = "test"
    chat_id: str = "test_chat"


def stub_origin(chat_id: str = "test_chat") -> StubOrigin:
    return StubOrigin(chat_id=chat_id)


def stub_agent() -> Any:
    from types import SimpleNamespace
    async def _handle(raw):
        pass
    agent = SimpleNamespace(
        services=ServiceInstanceRegistry(),
        config=Config(),
        handle=_handle,
    )
    from commamatrix.components.server import Server
    agent.http_server = Server(agent)
    return agent


def make_dialog_item(
    content: str = "hello",
    item_type: DialogItemType = DialogItemType.INPUT,
    role: DialogRole = DialogRole.USER,
    origin: DialogOrigin | None = None,
    user: str = "test_user",
    item_id: int | None = None,
    previous_item_id: int | None = None,
) -> DialogItem:
    return DialogItem(
        content=content,
        item_type=item_type,
        role=role,
        origin=origin or stub_origin(),
        user=user,
        item_id=item_id,
        previous_item_id=previous_item_id,
    )


def make_tool_descriptor(
    name: str = "test_tool",
    alias: str = "test_mod",
    namespace: str = "test_mod",
    doc: str = "A test tool.",
    schema: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    source: Any = None,
) -> ToolDescriptor:
    if source is None:
        from commamatrix.components.tool import PythonToolSource
        source = PythonToolSource()
    return ToolDescriptor(
        id=f"python://{namespace}/{name}",
        namespace=namespace,
        alias=alias,
        name=name,
        doc=doc,
        schema=schema or {
            "type": "function",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        meta=meta or {},
        _source_ref=weakref.ref(source),
    )


@dataclass
class FakeService(AbstractService):
    started: bool = False
    stopped: bool = False
    refreshed: bool = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def refresh(self) -> None:
        self.refreshed = True
