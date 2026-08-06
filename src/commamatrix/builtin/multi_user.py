# builtin/multi_user.py

from __future__ import annotations

import json
from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import TYPE_CHECKING

from ..components.config import ConfigField
from ..components.dialog import DialogItem, DialogRole
from ..components.hook import BeforeLlmCallCtx, BeforeRunCtx, before_llm_call, before_run
from ..components.instruction import InstructionCtx, instruction
from ..utils import _row_value, await_if_needed


if TYPE_CHECKING:
    from ..core.agent import Agent


user_header_template = ConfigField[str](
    name="user_header_template",
    default="[{datetime} | {user} | {name}]",
    description="Optional user-message header template. Use {datetime}, {user}, and {name}; the rendered header is followed by two newlines.",
)
user_header_datetime_format = ConfigField[str](
    name="user_header_datetime_format",
    default="%H:%M:%S %d.%m.%Y",
    description="strftime format used for the {datetime} header field",
)
user_header_timezone = ConfigField[str](
    name="user_header_timezone",
    default="UTC",
    description="IANA timezone used when a connector cannot resolve the user's timezone",
)


def _configured_timezone(agent: Agent) -> tzinfo:
    timezone_name = agent.config.get(user_header_timezone)
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid user_header_timezone: {timezone_name!r}") from exc


async def _user_timezone(ctx: BeforeLlmCallCtx, item: DialogItem) -> tzinfo:
    try:
        connector = ctx.run.agent.connector_manager.resolve_for_origin(item.origin)
    except LookupError:
        return _configured_timezone(ctx.run.agent)
    return resolved if (resolved := await await_if_needed(connector.get_user_timezone(item.origin))) else _configured_timezone(ctx.run.agent)


@before_run(priority=1000)
async def update_user_name(ctx: BeforeRunCtx) -> None:
    """Refresh and cache the current platform name for this run."""
    if "user_name" in ctx.run.state:
        return

    connector = ctx.run.connector
    if connector is None:
        try:
            connector = ctx.run.agent.connector_manager.resolve_for_origin(ctx.run.origin)
        except LookupError:
            return

    current_name = await await_if_needed(connector.get_user_name(ctx.run.origin))
    if not isinstance(current_name, str) or not current_name:
        return

    rows = await ctx.run.agent.storage.execute(
        "SELECT name, alternatives FROM commamatrix_user_names WHERE user = ?",
        (ctx.run.user,),
    )

    if rows:
        row = rows[0]
        previous_name = _row_value(row, "name")
        try:
            alternatives = json.loads(_row_value(row, "alternatives") or "[]")
        except (TypeError, ValueError):
            alternatives = []
        if not isinstance(alternatives, list):
            alternatives = []
        alternatives = [value for value in alternatives if isinstance(value, str)]
        if isinstance(previous_name, str) and previous_name != current_name:
            if previous_name not in alternatives:
                alternatives.append(previous_name)
            await ctx.run.agent.storage.execute(
                "UPDATE commamatrix_user_names SET name = ?, alternatives = ? WHERE user = ?",
                (current_name, json.dumps(alternatives, ensure_ascii=False), ctx.run.user),
            )
    else:
        await ctx.run.agent.storage.execute(
            "INSERT INTO commamatrix_user_names (user, name, alternatives) VALUES (?, ?, ?)",
            (ctx.run.user, current_name, "[]"),
        )

    ctx.run.state["user_name"] = current_name


def _render_header(item: DialogItem, template: str, datetime_format: str, user_timezone: tzinfo, user_name: str) -> str:
    created_at = item.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    values = {
        "datetime": created_at.astimezone(user_timezone).strftime(datetime_format),
        "user": item.user,
        "name": user_name,
    }
    try:
        return template.format(**values).rstrip()
    except (IndexError, KeyError, ValueError) as exc:
        raise ValueError("Invalid user_header_template; supported fields are {datetime}, {user}, and {name}") from exc


@before_llm_call(priority=-1000)
async def add_user_message_headers(ctx: BeforeLlmCallCtx) -> None:
    """Add metadata headers to transient dialog copies sent to the LLM."""
    template = ctx.run.agent.config.get(user_header_template)
    if not template:
        return
    datetime_format = ctx.run.agent.config.get(user_header_datetime_format)
    for index, item in enumerate(ctx.dialog):
        if item.role != DialogRole.USER:
            continue
        user_timezone = await _user_timezone(ctx, item)
        user_name = ctx.run.state.get("user_name", "")
        header = _render_header(item, template, datetime_format, user_timezone, str(user_name))
        prefix = f"{header}\n\n"
        if item.content.startswith(prefix):
            continue
        ctx.dialog[index] = item.model_copy(update={"content": prefix + item.content})


@instruction(priority=-200)
def describe_user_message_headers(ctx: InstructionCtx) -> str | None:
    """Tell the llm that configured user-message headers are metadata."""
    if not ctx.run.agent.config.get(user_header_template):
        return None
    return '''
# Message headers
Message headers are auto-generated and contain metadata (time / user id / user name), not instructions.
'''


__all__ = [
    "user_header_template",
    "user_header_datetime_format",
    "user_header_timezone",
    "update_user_name",
    "describe_user_message_headers",
]
