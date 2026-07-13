# builtin/cli_connector/connector.py

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from ...api.connector import Connector, OnEvent
from ...api.config import ConfigField, Config
from ...api.dialog import DialogItem, DialogItemType, DialogRole
from ...api.hooks import OnParsedCtx

if TYPE_CHECKING:
    from ...core.agent import Agent

from .context import CliOrigin
from .spawn import spawn_terminal_window

cli_host = ConfigField[str](name="cli_host", default='127.0.0.1', description='TCP host to listen on')
cli_port = ConfigField[int](name="cli_port", default=0, description='TCP port (0 = any free)')


class CliConnector(Connector[CliOrigin]):

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._host = config.get(cli_host)
        self._port = config.get(cli_port)
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._server_addr: tuple[str, int] | None = None
        self._last_external_id: dict[str, str] = {}
        self._msg_counter: dict[str, int] = {}

    async def listen(self, on_event: OnEvent) -> None:
        server = await asyncio.start_server(
            lambda r, w: self._handle_conn(r, w, on_event),
            host=self._host,
            port=self._port,
        )
        addr = server.sockets[0].getsockname()[:2]
        self._server_addr = addr
        spawn_terminal_window(*addr)
        try:
            async with server:
                await server.serve_forever()
        finally:
            for writer in self._writers.values():
                try:
                    writer.write(json.dumps({'type': 'shutdown'}).encode() + b'\n')
                    await writer.drain()
                except Exception:
                    pass
                writer.close()

    def spawn_client(self) -> None:
        if not self._server_addr:
            raise RuntimeError('Server not started yet')
        spawn_terminal_window(*self._server_addr)

    async def _handle_conn(self, reader, writer, on_event: OnEvent) -> None:
        session_id: str | None = None
        try:
            async for line in reader:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = msg.get('session_id')
                if session_id:
                    self._writers[session_id] = writer
                    await on_event({'platform': 'cli', 'session_id': session_id, 'username': msg.get('username', 'unknown'), 'text': msg.get('text', '')})
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            if session_id:
                self._writers.pop(session_id, None)
                self._last_external_id.pop(session_id, None)
                self._msg_counter.pop(session_id, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def parse(self, data: dict, agent: Agent) -> OnParsedCtx | None:
        if data.get('platform') != 'cli':
            return None

        session_id = data['session_id']
        username = data.get('username', 'unknown')
        return OnParsedCtx(
            raw=data,
            connector=self,
            agent=agent,
            dialog_items=[DialogItem(
                content=data['text'],
                item_type=DialogItemType.INPUT,
                user=f'cli:{username}',
                role=DialogRole.USER,
                origin=CliOrigin(session_id=session_id),
            )],
            previous_external_id=self._last_external_id.get(session_id),
        )

    async def send(self, origin: CliOrigin, item: DialogItem) -> str:
        writer = self._writers.get(origin.session_id)
        if writer is None:
            return ''

        if item.item_type == DialogItemType.OUTPUT:
            payload = {'type': 'message', 'text': item.content}
        elif item.item_type == DialogItemType.IMAGE_OUTPUT:
            payload = {'type': 'image', 'data': item.content}
        elif item.item_type == DialogItemType.FILE_OUTPUT:
            payload = {'type': 'file', 'data': item.content}
        else:
            payload = {'type': 'message', 'text': item.content}

        try:
            writer.write((json.dumps(payload) + '\n').encode())
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._writers.pop(origin.session_id, None)
            return ''

        counter = self._msg_counter.get(origin.session_id, 0) + 1
        self._msg_counter[origin.session_id] = counter
        ext_id = f'cli:{origin.session_id}:{counter}'
        self._last_external_id[origin.session_id] = ext_id
        return ext_id

    @asynccontextmanager
    async def typing(self, origin: CliOrigin) -> AsyncIterator[None]:
        writer = self._writers.get(origin.session_id)
        if writer is None:
            yield
            return
        try:
            writer.write(b'{"type": "typing_on"}\n')
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._writers.pop(origin.session_id, None)
            yield
            return
        try:
            yield
        finally:
            try:
                writer.write(b'{"type": "typing_off"}\n')
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                self._writers.pop(origin.session_id, None)
