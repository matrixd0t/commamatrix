# builtin/codeact/rpc/tcp.py

"""Authenticated length-prefixed JSON transport over TCP."""

from __future__ import annotations

import asyncio
import hmac
import json
import struct
from typing import Any

from .transport import Transport


def _write_msg(writer: asyncio.StreamWriter, data: bytes) -> None:
    header = struct.pack("!I", len(data))
    writer.write(header + data)


async def _read_msg(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    length = struct.unpack("!I", header)[0]
    return await reader.readexactly(length)


class TcpTransport(Transport):
    """Bidirectional length-prefixed JSON transport for local CodeAct workers."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._write_lock = asyncio.Lock()

    @classmethod
    async def connect(cls, host: str, port: int, token: str, *, timeout: float | None = None) -> TcpTransport:
        async def open_connection() -> TcpTransport:
            reader, writer = await asyncio.open_connection(host, port)
            transport = cls(reader, writer)
            try:
                await transport.send({"type": "hello", "token": token})
                response = await transport.recv()
                if response.get("type") != "hello_ok":
                    raise PermissionError("TCP handshake rejected")
            except BaseException:
                await transport.close()
                raise
            return transport

        if timeout is None:
            return await open_connection()
        return await asyncio.wait_for(open_connection(), timeout=timeout)

    @classmethod
    async def accept(cls, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, token: str, *, timeout: float | None = None) -> TcpTransport:
        transport = cls(reader, writer)
        try:
            if timeout is None:
                hello = await transport.recv()
            else:
                hello = await asyncio.wait_for(transport.recv(), timeout=timeout)
            supplied = hello.get("token") if hello.get("type") == "hello" else None
            if not isinstance(supplied, str) or not hmac.compare_digest(supplied, token):
                raise PermissionError("Invalid CodeAct TCP token")
            await transport.send({"type": "hello_ok"})
            return transport
        except BaseException:
            await transport.close()
            raise

    async def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        async with self._write_lock:
            if self._writer.is_closing():
                raise ConnectionError("TCP writer is closed")
            _write_msg(self._writer, data)
            await self._writer.drain()

    async def recv(self) -> dict[str, Any]:
        data = await _read_msg(self._reader)
        message = json.loads(data.decode("utf-8"))
        if not isinstance(message, dict):
            raise ValueError("RPC message must be a JSON object")
        return message

    async def close(self, timeout: float = 5.0) -> None:
        if self._writer.is_closing():
            return
        self._writer.close()
        try:
            await asyncio.wait_for(self._writer.wait_closed(), timeout=timeout)
        except (TimeoutError, ConnectionError, OSError):
            pass


class TcpServer:
    """Accept one token-authenticated TCP transport for a worker backend."""

    def __init__(self, token: str, host: str = "127.0.0.1", handshake_timeout: float = 10.0) -> None:
        self._token = token
        self._host = host
        self._handshake_timeout = handshake_timeout
        self._server: asyncio.AbstractServer | None = None
        self._connection: asyncio.Future[TcpTransport] | None = None

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("TCP http_server is not started")
        host, port = self._server.sockets[0].getsockname()[:2]
        return host, port

    async def start(self) -> tuple[str, int]:
        if self._server is not None:
            raise RuntimeError("TCP http_server is already started")
        self._connection = asyncio.get_running_loop().create_future()
        self._server = await asyncio.start_server(self._handle_connection, host=self._host, port=0)
        return self.address

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            transport = await TcpTransport.accept(reader, writer, self._token, timeout=self._handshake_timeout)
        except Exception:  # noqa: BLE001
            return
        connection = self._connection
        if connection is None or connection.done():
            await transport.close()
            return
        if self._server is not None:
            self._server.close()
        connection.set_result(transport)

    async def accept(self, timeout: float | None = None) -> TcpTransport:
        if self._connection is None:
            raise RuntimeError("TCP http_server is not started")
        if timeout is None:
            return await self._connection
        return await asyncio.wait_for(self._connection, timeout=timeout)

    async def close(self, timeout: float = 5.0) -> None:
        if self._server is None:
            return
        self._server.close()
        try:
            await asyncio.wait_for(self._server.wait_closed(), timeout=timeout)
        except TimeoutError:
            pass
        if self._connection is not None and not self._connection.done():
            self._connection.cancel()
        self._server = None
