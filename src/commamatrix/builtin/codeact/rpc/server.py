# builtin/codeact/rpc/server.py

"""RPC server — dispatches tool requests from the child process."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .protocol import (
    Namespace,
    RPCError,
    RPCRequest,
    RPCResponse,
    ToolsMethod,
)
from ....components.llm_adapter import ToolCall
from ....core.utils import to_jsonable

if TYPE_CHECKING:
    from ....components.hook import BeforeToolCallCtx


class RPCServer:
    """Handles inbound RPC calls, routing ``tools.*`` methods."""

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
            case Namespace.TOOLS:
                return await self._dispatch_tools(parts[1:], params)
        raise RPCError(code=-32601, message=f"Unknown namespace: {parts[0]}")

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
                from ..service import CodeActService as _CAM
                runtime = self._ctx.run.agent.services.require(_CAM)
                result = await runtime.invoke_tool(self._ctx, tool_call)
                return to_jsonable(result)

            case ToolsMethod.SEARCH:
                from ..service import CodeActService as _CAM
                runtime = self._ctx.run.agent.services.get(_CAM)
                if runtime is None:
                    raise RPCError(code=-32603, message="CodeActService not available")
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


def _make_serializable(obj: Any) -> Any:
    result = to_jsonable(obj)
    if isinstance(result, dict):
        result.pop("agent", None)
    return result


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
