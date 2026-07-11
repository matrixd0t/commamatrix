# builtin/codeact/rpc/client.py

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from .protocol import RPCError, RPCRequest, RPCResponse
from .transport import Transport


class RPCClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._pending: dict[str, asyncio.Future[RPCResponse]] = {}

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        req_id = uuid4().hex
        request = RPCRequest(id=req_id, method=method, params=params or {})
        future: asyncio.Future[RPCResponse] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        await self._transport.send(_serialize_request(request))
        response = await future
        if response.error is not None:
            raise RPCError(response.error.code, response.error.message, response.error.data)
        return response.result

    def feed_response(self, raw: dict[str, Any]) -> None:
        response = _deserialize_response(raw)
        future = self._pending.pop(response.id, None)
        if future is not None and not future.done():
            future.set_result(response)

    async def close(self) -> None:
        await self._transport.close()


def _serialize_request(req: RPCRequest) -> dict[str, Any]:
    return {"id": req.id, "method": req.method, "params": req.params}


def _deserialize_response(raw: dict[str, Any]) -> RPCResponse:
    error = None
    if "error" in raw and raw["error"] is not None:
        e = raw["error"]
        error = RPCError(code=e["code"], message=e["message"], data=e.get("data"))
    return RPCResponse(id=raw["id"], result=raw.get("result"), error=error)
