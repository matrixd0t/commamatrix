# builtin/storage_utils.py

from __future__ import annotations

from json import dumps
from typing import Any

from ..components.hook import BeforeToolCallCtx
from ..components.instruction import InstructionCtx, instruction
from ..components.tool import tool
from ..components.storage import Storage
from ..utils import to_jsonable


def _row_to_dict(row: Any) -> dict[str, Any] | Any:
    if isinstance(row, dict):
        return row
    keys = getattr(row, "keys", None)
    if keys is None:
        return row
    return {key: row[key] for key in keys()}


async def _schema_text(storage: Storage, tables: list[str]) -> str:
    table_text = ("\n" + "\n".join(tables)) or "none"
    return f"# Storage\nType: {await storage.info()}.\nTables (DDL):{table_text}."


@tool(alias="storage")
async def query(_query: str, params: list | None = None, *, ctx: BeforeToolCallCtx) -> str:
    """
    Execute SQL against persistent storage and return serialized results.
    Use RETURNING for INSERT, UPDATE, or DELETE when changed rows are needed.
    """
    rows = await ctx.run.agent.storage.execute(_query, tuple(params or ()))
    normalized_rows = [_row_to_dict(row) for row in rows]
    return dumps(to_jsonable(normalized_rows), ensure_ascii=False)


@instruction(priority=-60)
async def persistent_storage(ctx: InstructionCtx) -> str:
    """Describe the active persistent storage and its current tables."""
    storage: Storage = ctx.run.agent.storage.active
    try:
        tables = await ctx.run.agent.storage.schema()
    except Exception as exc:
        return f"# Storage\nType: {await storage.info()}.\nTables unavailable: {exc}."
    return await _schema_text(storage, tables)
