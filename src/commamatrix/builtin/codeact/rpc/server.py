# builtin/codeact/rpc/server.py

"""RPC server — dispatches context and tool requests from the child process."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .protocol import (
    ContextField,
    Namespace,
    RPCError,
    RPCRequest,
    RPCResponse,
    StorageMethod,
    ToolsMethod,
)
from ..manager import CodeActManager
from ....api.dialog import DialogItem, resolve_origin_type
from ....api.llm_adapter import ToolCall
from ....api.utils import to_jsonable

if TYPE_CHECKING:
    from ....api.hooks import BeforeToolCallCtx


class RPCServer:
    """Handles inbound RPC calls, routing ``context.*`` and ``tools.*`` methods."""

    def __init__(self, ctx: BeforeToolCallCtx) -> None:
        self._ctx = ctx
        self._request_id: str = ""

    async def handle(self, raw: dict[str, Any]) -> dict[str, Any]:
        request = _deserialize_request(raw)
        self._request_id = request.id
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
        match parts[0]:
            case Namespace.CONTEXT:
                return await self._dispatch_context(parts[1:], params)
            case Namespace.TOOLS:
                return await self._dispatch_tools(parts[1:], params)
        raise RPCError(code=-32601, message=f"Unknown namespace: {parts[0]}")

    async def _dispatch_context(self, path: list[str], params: dict[str, Any]) -> Any:
        if not path:
            raise RPCError(code=-32600, message="Empty context path")
        match path[0]:
            case ContextField.RUN:
                return _resolve_path(self._ctx.run, path[1:])
            case ContextField.TOOL_CALL:
                return _resolve_path(self._ctx.tool_call, path[1:])
            case ContextField.META:
                return _resolve_path(self._ctx.meta, path[1:])
            case ContextField.STORAGE:
                return await self._dispatch_storage(path[1:], params)
        raise RPCError(code=-32601, message=f"Unknown context field: {path[0]}")

    async def _dispatch_storage(self, path: list[str], params: dict[str, Any]) -> Any:
        if not path:
            raise RPCError(code=-32600, message="Empty storage method")
        storage = self._ctx.run.agent.storage
        args, kwargs = _call_arguments(params)
        match path[0]:
            case StorageMethod.SAVE_EVENT:
                item_data = kwargs.get("item", args[0] if args else None)
                if not isinstance(item_data, dict):
                    raise RPCError(code=-32602, message="save_event.item must be an object")
                return await storage.save_event(_parse_dialog_item(item_data))
            case StorageMethod.GET_BRANCH:
                item_id = kwargs.get("last_item_id", args[0] if args else None)
                if not isinstance(item_id, int):
                    raise RPCError(
                        code=-32602, message="get_branch.last_item_id must be an integer"
                    )
                return await storage.get_branch(item_id)
            case StorageMethod.FIND_ITEM_ID_BY_EXTERNAL_ID:
                external_id = kwargs.get("external_id", args[0] if args else None)
                origin_data = kwargs.get("origin", args[1] if len(args) > 1 else None)
                if not isinstance(external_id, str) or not isinstance(origin_data, dict):
                    raise RPCError(code=-32602, message="Invalid external ID or origin")
                return await storage.find_item_id_by_external_id(
                    external_id, _parse_origin(origin_data)
                )
        raise RPCError(code=-32601, message=f"Unknown storage method: {path[0]}")

    async def _dispatch_tools(self, path: list[str], params: dict[str, Any]) -> Any:
        if not path:
            raise RPCError(code=-32600, message="Empty tools method")
        match path[0]:
            case ToolsMethod.INVOKE:
                data = params.get("tool_call", params)
                tool_name = data.get("tool_id") or data["tool_name"]
                tool_call = ToolCall(
                    tool_call_id=data.get("tool_call_id") or self._request_id,
                    tool_name=tool_name,
                    tool_args=data.get("tool_args", {}),
                )
                runtime = self._ctx.run.agent.services.require(CodeActManager)
                result = await runtime.invoke_tool(self._ctx, tool_call)
                return to_jsonable(result)

            case ToolsMethod.SEARCH:
                runtime = self._ctx.run.agent.services.get(CodeActManager)
                if runtime is None:
                    raise RPCError(code=-32603, message="CodeActManager not available")
                return runtime.searcher.search(
                    params["query"], limit=params.get("limit", 5)
                )

            case ToolsMethod.SCHEMAS:
                return self._ctx.run.agent.tool_manager.schemas()
            case ToolsMethod.RESOLVE:
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
            case ToolsMethod.ALIASES:
                return list(self._ctx.run.agent.tool_manager.modules.keys())
            case ToolsMethod.LIST:
                alias = params["alias"]
                return [
                    {
                        "id": descriptor.id,
                        "name": descriptor.name,
                        "doc": descriptor.doc,
                        "schema": descriptor.schema,
                        "meta": descriptor.meta,
                    }
                    for descriptor in self._ctx.run.agent.tool_manager.modules.get(alias, [])
                ]
        raise RPCError(code=-32601, message=f"Unknown tools method: {path[0]}")


def _call_arguments(params: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    """Parse params in ``{"args": [...], "kwargs": {...}}`` or flat format.

    The structured format is used by ``_RemoteCall`` in the worker (stdio transport).
    The flat fallback exists for compatibility with alternative backends (e.g. HTTP JSON-RPC).
    """
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
    result = to_jsonable(obj)
    if isinstance(result, dict):
        result.pop("agent", None)
    return result


def _parse_origin(data: dict[str, Any]):
    return resolve_origin_type(data).model_validate(data)


def _parse_dialog_item(data: dict[str, Any]):
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
