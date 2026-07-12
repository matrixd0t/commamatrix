# builtin/codeact/rpc/server.py

"""RPC server — dispatches context and tool requests from the child process."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, TYPE_CHECKING

from .protocol import RPCError, RPCRequest, RPCResponse

if TYPE_CHECKING:
    from ....api.hooks import BeforeToolCallCtx


class RPCServer:
    """Handles inbound RPC calls, routing ``context.*`` and ``tools.*`` methods."""

    def __init__(self, ctx: BeforeToolCallCtx) -> None:
        self._ctx = ctx

    async def handle(self, raw: dict[str, Any]) -> dict[str, Any]:
        request = _deserialize_request(raw)
        try:
            result = await self._dispatch(request.method, request.params)
            response = RPCResponse(id=request.id, result=_make_serializable(result))
        except RPCError as exc:
            response = RPCResponse(id=request.id, error=exc)
        except Exception as exc:
            response = RPCResponse(
                id=request.id, error=RPCError(code=-32603, message=str(exc))
            )
        return _serialize_response(response)

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        parts = method.split(".")
        if not parts or not parts[0]:
            raise RPCError(code=-32600, message="Empty method")
        if parts[0] == "context":
            return await self._dispatch_context(parts[1:], params)
        if parts[0] == "tools":
            return await self._dispatch_tools(parts[1:], params)
        raise RPCError(code=-32601, message=f"Unknown namespace: {parts[0]}")

    async def _dispatch_context(self, path: list[str], params: dict[str, Any]) -> Any:
        if not path:
            raise RPCError(code=-32600, message="Empty context path")
        if path[0] == "run":
            return _resolve_path(self._ctx.run, path[1:])
        if path[0] == "tool_call":
            return _resolve_path(self._ctx.tool_call, path[1:])
        if path[0] == "meta":
            return _resolve_path(self._ctx.meta, path[1:])
        if path[0] == "storage":
            return await self._dispatch_storage(path[1:], params)
        raise RPCError(code=-32601, message=f"Unknown context field: {path[0]}")

    async def _dispatch_storage(self, path: list[str], params: dict[str, Any]) -> Any:
        if not path:
            raise RPCError(code=-32600, message="Empty storage method")
        storage = self._ctx.run.agent.storage
        args, kwargs = _call_arguments(params)
        method = path[0]

        if method == "save_event":
            item_data = kwargs.get("item", args[0] if args else None)
            if not isinstance(item_data, dict):
                raise RPCError(code=-32602, message="save_event.item must be an object")
            return await storage.save_event(_parse_dialog_item(item_data))
        if method == "get_branch":
            item_id = kwargs.get("last_item_id", args[0] if args else None)
            if not isinstance(item_id, int):
                raise RPCError(
                    code=-32602, message="get_branch.last_item_id must be an integer"
                )
            return await storage.get_branch(item_id)
        if method == "find_item_id_by_external_id":
            external_id = kwargs.get("external_id", args[0] if args else None)
            origin_data = kwargs.get("origin", args[1] if len(args) > 1 else None)
            if not isinstance(external_id, str) or not isinstance(origin_data, dict):
                raise RPCError(code=-32602, message="Invalid external ID or origin")
            return await storage.find_item_id_by_external_id(
                external_id, _parse_origin(origin_data)
            )
        raise RPCError(code=-32601, message=f"Unknown storage method: {method}")

    async def _dispatch_tools(self, path: list[str], params: dict[str, Any]) -> Any:
        if not path:
            raise RPCError(code=-32600, message="Empty tools method")
        method = path[0]

        if method == "invoke":
            from ..runtime import CodeActRuntime
            from ....api.llm_adapter import ToolCall

            data = params.get("tool_call", params)
            tool_call = ToolCall(
                tool_call_id=data.get("tool_call_id", ""),
                tool_name=data["tool_name"],
                tool_args=data.get("tool_args", {}),
            )
            runtime = self._ctx.run.agent.services.require(CodeActRuntime)
            return await runtime.invoke_tool(self._ctx, tool_call.tool_name, tool_call.tool_args)

        if method == "search":
            from ..runtime import CodeActRuntime

            runtime = self._ctx.run.agent.services.get(CodeActRuntime)
            if runtime is None:
                raise RPCError(code=-32603, message="CodeActRuntime not available")
            return runtime.searcher.search(
                params["query"], limit=params.get("limit", 5)
            )

        if method == "schemas":
            return self._ctx.run.agent.tool_manager.schemas()
        if method == "resolve":
            descriptor = self._ctx.run.agent.tool_manager.resolve(params["name"])
            if descriptor is None:
                return None
            return {
                "id": descriptor.id,
                "namespace": descriptor.namespace,
                "alias": descriptor.alias,
                "name": descriptor.name,
                "doc": descriptor.doc,
                "schema": descriptor.schema,
            }
        if method == "aliases":
            return list(self._ctx.run.agent.tool_manager.modules.keys())
        if method == "list":
            alias = params["alias"]
            return [
                {
                    "id": descriptor.id,
                    "name": descriptor.name,
                    "doc": descriptor.doc,
                    "schema": descriptor.schema,
                    "metadata": descriptor.metadata,
                }
                for descriptor in self._ctx.run.agent.tool_manager.modules.get(alias, [])
            ]
        raise RPCError(code=-32601, message=f"Unknown tools method: {method}")


def _call_arguments(params: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    if "args" in params or "kwargs" in params:
        args = params.get("args", [])
        kwargs = params.get("kwargs", {})
        return list(args) if isinstance(args, list) else [], dict(kwargs) if isinstance(
            kwargs, dict
        ) else {}
    return [], dict(params)


def _resolve_path(obj: Any, path: list[str]) -> Any:
    for part in path:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            obj = getattr(obj, part, None)
        if obj is None:
            return None
    return _make_serializable(obj)


def _make_serializable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(key): _make_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_make_serializable(value) for value in obj]
    if hasattr(obj, "model_dump"):
        return _make_serializable(obj.model_dump(mode="json"))
    if is_dataclass(obj):
        return {
            field.name: _make_serializable(getattr(obj, field.name))
            for field in fields(obj)
            if field.name != "agent"
        }
    if hasattr(obj, "__dict__"):
        return {
            key: _make_serializable(value)
            for key, value in obj.__dict__.items()
            if not key.startswith("_")
        }
    return str(obj)


def _parse_origin(data: dict[str, Any]):
    from ....api.dialog import resolve_origin_type

    return resolve_origin_type(data).model_validate(data)


def _parse_dialog_item(data: dict[str, Any]):
    from ....api.dialog import DialogItem

    item_data = dict(data)
    item_data["origin"] = _parse_origin(item_data["origin"])
    return DialogItem.model_validate(item_data)


def _deserialize_request(raw: dict[str, Any]) -> RPCRequest:
    return RPCRequest(id=raw["id"], method=raw["method"], params=raw.get("params", {}))


def _serialize_response(resp: RPCResponse) -> dict[str, Any]:
    result: dict[str, Any] = {"id": resp.id}
    if resp.error is not None:
        result["error"] = {"code": resp.error.code, "message": resp.error.message}
        if resp.error.data is not None:
            result["error"]["data"] = resp.error.data
    else:
        result["result"] = resp.result
    return result
