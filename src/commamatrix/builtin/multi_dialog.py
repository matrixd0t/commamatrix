# builtin/multi_dialog.py

from __future__ import annotations

import json

from ..components.dialog import DialogOrigin, ORIGIN_REGISTRY
from ..components.hook import AfterSendCtx, BeforeToolCallCtx, after_send
from ..components.instruction import InstructionCtx, instruction
from ..components.tool import tool
from ..utils import await_if_needed


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
    """Explain how to switch dialog origins."""
    return '''
# Switching dialogs
Use `dialogs_switch` with the `origin_type` value and a JSON string in `fields_json` containing the identity fields listed by `dialogs_get_origins`.
The decoded `fields_json` object must contain only origin identity fields, such as `http_user_id`.
Never put response text, `message`, or `content` into `fields_json`. Do not guess user names or ids: if unknown, use get_user_info().
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
        if origin_cls.__name__ == 'InternalOrigin':
            continue
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
async def get_user_info(user_names_or_ids: list[str | int], ctx: BeforeToolCallCtx) -> dict[str, dict[str, object]]:
    """Get user information keyed by each name or id from the input list.

    Usage: "user_names_or_ids": ["Alice", "http:42", "telegram:bob"]
    If a historical name matches, ``matched_name`` identifies the old name and ``username`` contains the user's current name.
    """
    results: dict[str, dict[str, object]] = {}
    connectors = ctx.run.agent.connector_manager.resolve()

    for user_name_or_id in user_names_or_ids:
        request_key = str(user_name_or_id)
        if isinstance(user_name_or_id, bool) or not isinstance(user_name_or_id, (str, int)):
            results[request_key] = {"error": "invalid input"}
            continue
        user_name_or_id = str(user_name_or_id).strip()
        if not user_name_or_id:
            results[request_key] = {"error": "invalid input"}
            continue

        platform_filter = None
        user_identifier = user_name_or_id
        if ":" in user_name_or_id:
            platform_filter, _, user_identifier = user_name_or_id.partition(":")
            platform_filter = platform_filter.strip()
            user_identifier = user_identifier.strip()
        if not user_identifier:
            results[request_key] = {"error": "invalid input"}
            continue

        try:
            numeric = int(user_identifier)
        except (ValueError, TypeError):
            numeric = None

        candidate_connectors = connectors
        if platform_filter:
            candidate_connectors = [
                connector
                for connector in connectors
                if platform_filter in {
                    origin_type.model_fields["platform"].default
                    for origin_type in connector.origin_types
                }
            ]
        if not candidate_connectors:
            results[request_key] = {
                "error": "No connectors found"
                + (f" for platform {platform_filter!r}" if platform_filter else "")
            }
            continue

        search_key = numeric if numeric is not None else user_identifier
        result: dict[str, object] | None = None
        for connector in candidate_connectors:
            found = await await_if_needed(connector.get_user_info(search_key))
            if not isinstance(found, dict):
                continue
            found_id = found.get("id")
            if not isinstance(found_id, (int, str)):
                continue
            username = found.get("username")
            if not isinstance(username, str):
                username = str(found_id)
            platform = platform_filter or str(
                next(
                    (
                        origin_type.model_fields["platform"].default
                        for origin_type in connector.origin_types
                    ),
                    "unknown",
                )
            )
            result = {
                "id": found_id,
                "username": username,
                "platform": platform,
            }
            if isinstance(found.get("matched_name"), str):
                result["matched_name"] = found["matched_name"]
            if found.get("name_changed"):
                result["name_changed"] = True
            break

        results[request_key] = result or {"error": "User not found"}

    return results


@tool(alias="dialogs")
async def switch(origin_type: str, fields_json: str, ctx: BeforeToolCallCtx) -> str:
    """Route the next response; fields_json must be a JSON object containing only origin identity fields."""
    origin_cls = _resolve_origin_class(origin_type)
    if origin_cls is None:
        return f"Unknown origin type: {origin_type}\nAvailable origins:\n{await get_origins()}"
    try:
        fields = json.loads(fields_json)
    except (json.JSONDecodeError, TypeError):
        return f"Invalid fields_json for origin type {origin_type!r}; expected a JSON object:\n{_origin_help(origin_cls)}"
    if not isinstance(fields, dict):
        return f"Invalid fields_json for origin type {origin_type!r}; expected a JSON object:\n{_origin_help(origin_cls)}"
    allowed_fields = set(origin_cls.model_fields) - set(DialogOrigin.model_fields)
    unknown_fields = set(fields) - allowed_fields
    if unknown_fields:
        return (
            f"Invalid fields_json for origin type {origin_type!r}: {sorted(unknown_fields)}\n"
            f"Expected fields:\n{_origin_help(origin_cls)}\n"
            "Do not include response text in fields_json."
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
    identity_fields = tuple(sorted(set(type(new_origin).model_fields) - set(DialogOrigin.model_fields)))
    if not identity_fields:
        ctx.run.user = f"{new_origin.platform}:unknown"
        return
    if len(identity_fields) != 1:
        identity = json.dumps(
            {
                field_name: getattr(new_origin, field_name)
                for field_name in identity_fields
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        ctx.run.user = f"{new_origin.platform}:{identity}"
        return

    identity = getattr(new_origin, identity_fields[0])
    connector = ctx.run.agent.connector_manager.resolve_for_origin(new_origin)
    user_info = await await_if_needed(connector.get_user_info(identity))

    resolved_id = user_info.get("id") if isinstance(user_info, dict) else None
    if resolved_id is None:
        resolved_id = identity
    ctx.run.user = f"{new_origin.platform}:{resolved_id}"


__all__ = [
    "get_origins",
    "get_user_info",
    "switch",
]



