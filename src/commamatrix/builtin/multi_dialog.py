# builtin/multi_dialog.py

from __future__ import annotations

import inspect
from typing import Any

from ..components.dialog import DialogOrigin, ORIGIN_REGISTRY
from ..components.hook import AfterSendCtx, BeforeToolCallCtx, after_send
from ..components.instruction import InstructionCtx, instruction
from ..components.tool import tool


def _type_name(annotation: object) -> str:
    origin = getattr(annotation, "__origin__", None)
    if origin is None:
        return getattr(annotation, "__name__", str(annotation))
    args = getattr(annotation, "__args__", ())
    if args:
        inner = ", ".join(_type_name(arg) for arg in args)
        return f"{_type_name(origin)}[{inner}]"
    return _type_name(origin)


@instruction(priority=-70)
def describe_dialog_switch(ctx: InstructionCtx) -> str:
    """Explain how to switch responses without mixing message text into origin fields."""
    return '''
# Switching dialogs
Use `dialogs_switch` with the `origin_type` value and identity fields listed by `dialogs_get_origins`.
The `fields` object must contain only origin identity fields, such as `http_user_id`.
Never put response text, `message`, or `content` into `fields`. Do not guess user name or id: if unknown, use get_user_info().
After `dialogs_switch` returns `OK`, send the user-facing response normally.
'''


def _resolve_origin_class(origin_type: str) -> type[DialogOrigin] | None:
    origin_cls = ORIGIN_REGISTRY.get(origin_type)
    if origin_cls is not None:
        return origin_cls
    matches = [
        origin_cls
        for origin_cls in ORIGIN_REGISTRY.values()
        if origin_cls.model_fields["origin_type"].default == origin_type
    ]
    return matches[0] if len(matches) == 1 else None


def _origin_help(origin_cls: type[DialogOrigin]) -> str:
    base_fields = set(DialogOrigin.model_fields)
    extra_fields = {
        name: info
        for name, info in origin_cls.model_fields.items()
        if name not in base_fields
    }
    type_name = origin_cls.model_fields["origin_type"].default
    if type_name == "unknown":
        type_name = origin_cls.__name__
    platform = origin_cls.model_fields["platform"].default
    if not extra_fields:
        return f"{platform}\n└─{type_name}"
    fields = ", ".join(f"{name} ({_type_name(info.annotation)})" for name, info in extra_fields.items())
    return f"{platform}\n└─{type_name}: {fields}"


@tool(alias="dialogs")
async def get_origins(platform: str = "any") -> str:
    """View field schemas for all available dialog origins optionally grouped by platform."""
    base_fields = set(DialogOrigin.model_fields)
    by_platform: dict[str, list[type[DialogOrigin]]] = {}
    for origin_cls in ORIGIN_REGISTRY.values():
        by_platform.setdefault(origin_cls.model_fields["platform"].default, []).append(origin_cls)

    lines: list[str] = []
    for origin_platform in sorted(by_platform):
        if platform != "any" and origin_platform != platform:
            continue
        lines.append(origin_platform)
        for origin_cls in sorted(by_platform[origin_platform], key=lambda cls: cls.__name__):
            extra_fields = {name: info for name, info in origin_cls.model_fields.items() if name not in base_fields}
            type_name = origin_cls.model_fields["origin_type"].default
            if type_name == "unknown":
                type_name = origin_cls.__name__
            if extra_fields:
                fields = ", ".join(f"{name} ({_type_name(info.annotation)})" for name, info in extra_fields.items())
                lines.append(f"└─{type_name}: {fields}")
            else:
                lines.append(f"└─{type_name}")
    return "\n".join(lines) if lines else "No origins registered"


@tool(alias="dialogs")
async def get_user_info(user_name_or_id: str, ctx: BeforeToolCallCtx) -> dict[str, int | str]:
    """
    Get user-related information: id, username and platform."""
    if not isinstance(user_name_or_id, str) or not user_name_or_id.strip():
        return {"error": "user_name_or_id is required"}
    user_name_or_id = user_name_or_id.strip()

    platform_filter, user_identifier = None, None
    if ":" in user_name_or_id:
        platform_filter, _, user_identifier = user_name_or_id.partition(":")
        platform_filter = platform_filter.strip()
        user_identifier = user_identifier.strip()
    if not user_identifier:
        user_identifier = user_name_or_id

    try:
        numeric = int(user_identifier)
    except (ValueError, TypeError):
        numeric = None

    connectors = ctx.run.agent.connector_manager.resolve()
    if platform_filter:
        connectors = [
            connector
            for connector in connectors
            if platform_filter in {
                origin_type.model_fields["platform"].default
                for origin_type in connector.origin_types
            }
        ]
    if not connectors:
        return {"error": "No connectors found" + (f" for platform {platform_filter!r}" if platform_filter else "")}

    search_key = numeric if numeric is not None else user_identifier
    for connector in connectors:
        resolver = getattr(connector, "get_user_info", None)
        if resolver is None:
            continue
        found = await resolver(search_key)
        if found is not None:
            platform = next(iter(connector.origin_types)).model_fields["platform"].default
            return {"id": found["id"], "username": found["username"], "platform": platform}

    return {"error": "User not found"}


@tool(alias="dialogs")
async def switch(origin_type: str, fields: dict[str, Any], ctx: BeforeToolCallCtx) -> str:
    """Route the next response; fields must contain only origin identity fields."""
    origin_cls = _resolve_origin_class(origin_type)
    if origin_cls is None:
        return f"Unknown origin type: {origin_type}\nAvailable origins:\n{get_origins()}"
    if not isinstance(fields, dict):
        return f"Invalid fields for origin type {origin_type!r}; expected a dictionary:\n{_origin_help(origin_cls)}"
    allowed_fields = set(origin_cls.model_fields) - set(DialogOrigin.model_fields)
    unknown_fields = set(fields) - allowed_fields
    if unknown_fields:
        return (
            f"Invalid fields for origin type {origin_type!r}: {sorted(unknown_fields)}\n"
            f"Expected fields:\n{_origin_help(origin_cls)}\n"
            "Do not include response text in fields."
        )
    try:
        origin = origin_cls.model_validate(fields)
        ctx.run.agent.connector_manager.resolve_for_origin(origin)
    except Exception as exc:
        return f"Invalid origin: {exc}"
    ctx.run.state["new_origin"] = origin
    return "OK"


@after_send
async def apply_new_origin(ctx: AfterSendCtx) -> None:
    """Apply a tool-requested origin after its result is persisted."""
    new_origin = ctx.run.state.pop("new_origin", None)
    if new_origin is None:
        return

    ctx.run.origin = new_origin
    identity_fields = set(type(new_origin).model_fields) - set(DialogOrigin.model_fields)
    if len(identity_fields) != 1:
        return

    identity = getattr(new_origin, next(iter(identity_fields)))
    connector = ctx.run.agent.connector_manager.resolve_for_origin(new_origin)
    resolver = getattr(connector, "get_user_info", None)
    if resolver is None:
        ctx.run.user = f"{new_origin.platform}:{identity}"
        return

    user_info = resolver(identity)
    if inspect.isawaitable(user_info):
        user_info = await user_info
    resolved_id = user_info.get("id", identity) if isinstance(user_info, dict) else identity
    ctx.run.user = f"{new_origin.platform}:{resolved_id}"


__all__ = [
    "get_origins",
    "get_user_info",
    "switch",
]
