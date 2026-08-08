# builtin/codeact/rpc/server.py

"""RPC http_server — dispatches tool requests from the child process."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....components.llm_adapter import ToolCall
from ....utils import to_jsonable
from .protocol import (
    Namespace,
    RPCError,
    RPCRequest,
    RPCResponse,
    ToolsMethod,
)

if TYPE_CHECKING:
    from ....components.hook import BeforeToolCallCtx
    from ....components.tool import ToolDescriptor


def is_codeact_internal(descriptor: ToolDescriptor) -> bool:
    """Return True if a descriptor must stay outside the CodeAct worker."""
    return not descriptor.meta.get("codeact", True)


def serialize_tool_descriptor(descriptor: ToolDescriptor) -> dict[str, Any]:
    return {
        "id": descriptor.id,
        "namespace": descriptor.namespace,
        "alias": descriptor.alias,
        "name": descriptor.name,
        "doc": descriptor.doc,
        "schema": descriptor.schema,
        "meta": descriptor.meta,
    }


def _make_serializable(obj: Any) -> Any:
    result = to_jsonable(obj)
    if isinstance(result, dict):
        result.pop("agent", None)
    return result


class RPCServer:
    """Handles inbound RPC calls, routing ``tools.*`` methods.

    Stateless — no per-request state stored on the instance.
    """

    def __init__(self, ctx: BeforeToolCallCtx) -> None:
        self._ctx = ctx

    async def handle(self, raw: dict[str, Any]) -> dict[str, Any]:
        request = _deserialize_request(raw)
        try:
            result = await self._dispatch(request.id, request.method, request.params)
            response = RPCResponse(id=request.id, result=_make_serializable(result))
        except RPCError as exc:
            response = RPCResponse(id=request.id, error=exc)
        except Exception as exc:
            response = RPCResponse(
                id=request.id, error=RPCError(code=-32603, message=str(exc))
            )
        return _serialize_response(response)

    async def _dispatch(self, request_id: str, method: str, params: dict[str, Any]) -> Any:
        parts = method.split(".")
        if not parts or not parts[0]:
            raise RPCError(code=-32600, message="Empty method")
        match parts[0]:
            case Namespace.TOOLS:
                return await self._dispatch_tools(request_id, parts[1:], params)
        raise RPCError(code=-32601, message=f"Unknown namespace: {parts[0]}")

    async def _dispatch_tools(self, request_id: str, path: list[str], params: dict[str, Any]) -> Any:
        if not path:
            raise RPCError(code=-32600, message="Empty tools method")
        match path[0]:
            case ToolsMethod.INVOKE:
                tool_id = params["tool_id"]
                descriptor = self._ctx.run.agent.tool_manager.resolve_id(tool_id)
                if descriptor is None:
                    raise RPCError(code=-32602, message=f"Tool not found: {tool_id!r}")
                if is_codeact_internal(descriptor):
                    raise RPCError(
                        code=-32603,
                        message=f"Internal tool with id {tool_id!r} is not accessible from CodeAct",
                    )
                tool_call = ToolCall(
                    tool_call_id=params.get("tool_call_id", ""),
                    tool_name=self._ctx.run.agent.tool_manager.public_name(descriptor),
                    tool_args=params.get("tool_args", {}),
                )
                from ..service import CodeActService as _CAM

                runtime = self._ctx.run.agent.services.require(_CAM)
                result = await runtime.invoke_tool(self._ctx, tool_call)
                return result

            case ToolsMethod.RESOLVE:
                descriptor = self._ctx.run.agent.tool_manager.resolve(params["name"])
                if descriptor is None or is_codeact_internal(descriptor):
                    return None
                return serialize_tool_descriptor(descriptor)
        raise RPCError(code=-32601, message=f"Unknown tools method: {path[0]}")


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
