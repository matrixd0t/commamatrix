# tests/test_filesystem_context.py

from __future__ import annotations

from types import SimpleNamespace

import pytest

from commamatrix.builtin.filesystem import add_agents_file
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogOrigin, DialogRole
from commamatrix.components.hook import BeforeLlmCallCtx


def _item(content: str, role: DialogRole) -> DialogItem:
    return DialogItem(
        content=content,
        item_type=DialogItemType.INPUT,
        role=role,
        origin=DialogOrigin(),
    )


@pytest.mark.asyncio
async def test_agents_file_is_inserted_after_system_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents.md").write_text("\n  Keep this rule.  \n", encoding="utf-8")
    run = SimpleNamespace(origin=DialogOrigin())
    ctx = BeforeLlmCallCtx(
        run=run,
        dialog=[_item("Generated instructions", DialogRole.SYSTEM), _item("Hello", DialogRole.USER)],
        tools=[],
    )

    await add_agents_file(ctx)

    assert [item.role for item in ctx.dialog] == [
        DialogRole.SYSTEM,
        DialogRole.SYSTEM,
        DialogRole.USER,
    ]
    assert ctx.dialog[1].content == "Keep this rule."


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, "", " \n\t"])
async def test_empty_or_missing_agents_file_is_skipped(tmp_path, monkeypatch, content):
    monkeypatch.chdir(tmp_path)
    if content is not None:
        (tmp_path / "agents.md").write_text(content, encoding="utf-8")
    ctx = BeforeLlmCallCtx(
        run=SimpleNamespace(origin=DialogOrigin()),
        dialog=[_item("Hello", DialogRole.USER)],
        tools=[],
    )

    await add_agents_file(ctx)

    assert len(ctx.dialog) == 1
