# tests/test_multi_dialog.py

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from commamatrix.builtin.multi_dialog import get_user_info
from commamatrix.builtin.multi_user import (
    add_user_message_headers,
    describe_user_message_headers,
    update_user_name,
    user_header_datetime_format,
    user_header_renderer,
)
from commamatrix.components.config import Config
from commamatrix.components.connector import UserInfo
from commamatrix.components.dialog import (
    DialogItem,
    DialogItemType,
    DialogOrigin,
    DialogRole,
)
from commamatrix.components.hook import BeforeLlmCallCtx, BeforeRunCtx, RunCtx
from commamatrix.components.instruction import InstructionCtx


class TelegramOriginForMultiDialog(DialogOrigin):
    origin_type: str = "telegram_test"
    platform: str = "telegram"
    user_id: int


def _agent(config: Config, connector=None):
    def resolve_for_origin(_origin):
        if connector is None:
            raise LookupError
        return connector

    return SimpleNamespace(
        config=config,
        connector_manager=SimpleNamespace(resolve_for_origin=resolve_for_origin),
    )


def _item() -> DialogItem:
    return DialogItem(
        content="привет",
        item_type=DialogItemType.INPUT,
        role=DialogRole.USER,
        origin=TelegramOriginForMultiDialog(user_id=12345),
        user="telegram:Елена",
        created_at=datetime(2026, 5, 24, 11, 0, 0, tzinfo=UTC),
    )


class _Storage:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    async def execute(self, query, params=()):
        self.calls.append((query, params))
        return self.rows


@pytest.mark.asyncio
async def test_user_message_header_is_added_to_a_transient_copy():
    agent = _agent(Config({
        user_header_renderer: lambda _run, item: f"[custom | {item.user}]",
    }))
    item = _item()
    ctx = BeforeLlmCallCtx(run=RunCtx(agent=agent, origin=item.origin, user=item.user), dialog=[item], tools=[])

    await add_user_message_headers(ctx)

    assert item.content == "привет"
    assert ctx.dialog[0].content == "[custom | telegram:Елена]\n\nпривет"


@pytest.mark.asyncio
async def test_user_message_header_uses_connector_timezone():
    async def get_user_timezone(_run, _user):
        return ZoneInfo("Europe/Moscow")

    connector = SimpleNamespace(get_user_timezone=get_user_timezone)
    agent = _agent(Config({
        user_header_datetime_format: "%H:%M:%S %d.%m.%Y",
    }), connector)
    item = _item()
    ctx = BeforeLlmCallCtx(run=RunCtx(agent=agent, connector=connector, origin=item.origin, user=item.user), dialog=[item], tools=[])

    await add_user_message_headers(ctx)

    assert ctx.dialog[0].content == "[14:00:00 24.05.2026] telegram:Елена | :\n\nпривет"


@pytest.mark.asyncio
async def test_user_name_is_not_filled_with_user_id_without_connector():
    agent = _agent(Config())
    agent.storage = _Storage()
    item = _item()
    ctx = BeforeRunCtx(run=RunCtx(agent=agent, origin=item.origin, user=item.user))

    await update_user_name(ctx)

    assert ctx.run.state == {}
    assert agent.storage.calls == []


@pytest.mark.asyncio
async def test_user_name_is_not_stored_when_connector_cannot_resolve_it():
    async def get_user_info(_user):
        return None

    connector = SimpleNamespace(get_user_info=get_user_info)
    agent = _agent(Config(), connector)
    agent.storage = _Storage()
    item = _item()
    ctx = BeforeRunCtx(run=RunCtx(agent=agent, origin=item.origin, user=item.user))

    await update_user_name(ctx)

    assert ctx.run.state == {}
    assert agent.storage.calls == []


@pytest.mark.asyncio
async def test_user_message_header_uses_empty_name_when_name_is_unavailable():
    agent = _agent(Config({
        user_header_datetime_format: "%H:%M:%S %d.%m.%Y",
    }))
    item = _item()
    ctx = BeforeLlmCallCtx(run=RunCtx(agent=agent, origin=item.origin, user=item.user), dialog=[item], tools=[])

    await add_user_message_headers(ctx)

    assert ctx.dialog[0].content == "[14:00:00 24.05.2026] telegram:Елена | :\n\nпривет"


@pytest.mark.asyncio
async def test_user_info_uses_connector_for_platform():
    async def lookup(user):
        assert user == "Елена"
        return UserInfo(id=12345, name="Елена")

    connector = SimpleNamespace(origin_types=(TelegramOriginForMultiDialog,), get_user_info=lookup)
    agent = SimpleNamespace(connector_manager=SimpleNamespace(resolve=lambda: [connector]))
    ctx = SimpleNamespace(run=SimpleNamespace(agent=agent))

    assert await get_user_info(["telegram:Елена"], ctx) == {
        "telegram:Елена": {
            "id": 12345,
            "username": "Елена",
            "platform": "telegram",
        }
    }


@pytest.mark.asyncio
async def test_user_message_header_is_optional_and_instruction_is_dynamic():
    agent = _agent(Config(overrides={user_header_renderer: None}))
    item = _item()
    ctx = BeforeLlmCallCtx(run=RunCtx(agent=agent, origin=item.origin, user=item.user), dialog=[item], tools=[])
    await add_user_message_headers(ctx)
    run = ctx.run

    assert item.content == "привет"
    assert describe_user_message_headers(InstructionCtx(run=run)) is None

    agent.config.set(user_header_renderer, lambda _run, _item: "[custom]")

    assert describe_user_message_headers(InstructionCtx(run=run)) is not None
