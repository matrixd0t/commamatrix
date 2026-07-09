from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from ...api.connector import Connector, ListensEvents, OnEvent
from ...api.config import ConfigField
from ...api.dialog import DialogItem, DialogItemType, DialogRole
from ...api.hooks import OnParsedCtx

if TYPE_CHECKING:
    from ...core.agent import Agent

from .context import CliOrigin
from .spawn import spawn_terminal_window


host = ConfigField[str](default='127.0.0.1', description='TCP host to listen on')
port = ConfigField[int](default=0, description='TCP port (0 = any free)')


class CliConnector(Connector[CliOrigin], ListensEvents):
    _writers: dict[str, asyncio.StreamWriter] = {}
    _server_addr: tuple[str, int] | None = None
    _last_external_id: dict[str, str] = {}
    _msg_counter: dict[str, int] = {}

    @classmethod
    async def listen(cls, on_event: OnEvent) -> None:
        server = await asyncio.start_server(
            lambda r, w: cls._handle_conn(r, w, on_event),
            host=host.get(),
            port=port.get(),
        )
        addr = server.sockets[0].getsockname()[:2]
        cls._server_addr = addr
        spawn_terminal_window(*addr)
        try:
            async with server:
                await server.serve_forever()
        finally:
            for writer in cls._writers.values():
                try:
                    writer.write(json.dumps({'type': 'shutdown'}).encode() + b'\n')
                    await writer.drain()
                except Exception:
                    pass
                writer.close()

    @classmethod
    def spawn_client(cls) -> None:
        if not cls._server_addr:
            raise RuntimeError('Server not started yet')
        spawn_terminal_window(*cls._server_addr)

    @classmethod
    async def _handle_conn(cls, reader, writer, on_event: OnEvent) -> None:
        session_id: str | None = None
        try:
            async for line in reader:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = msg.get('session_id')
                if session_id:
                    cls._writers[session_id] = writer
                    await on_event({'platform': 'cli', 'session_id': session_id, 'username': msg.get('username', 'unknown'), 'text': msg.get('text', '')})
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            if session_id:
                cls._writers.pop(session_id, None)
                cls._last_external_id.pop(session_id, None)
                cls._msg_counter.pop(session_id, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @classmethod
    async def parse(cls, data: dict, agent: type[Agent]) -> OnParsedCtx | None:
        if data.get('platform') != 'cli':
            return None

        session_id = data['session_id']
        username = data.get('username', 'unknown')
        return OnParsedCtx(
            raw=data,
            connector=cls,
            agent=agent,
            dialog_items=[DialogItem(
                content=data['text'],
                item_type=DialogItemType.INPUT,
                user=f'cli:{username}',
                role=DialogRole.USER,
                origin=CliOrigin(session_id=session_id),
            )],
            previous_external_id=cls._last_external_id.get(session_id),
        )

    @classmethod
    async def send(cls, origin: CliOrigin, item: DialogItem) -> str:
        writer = cls._writers.get(origin.session_id)
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
            cls._writers.pop(origin.session_id, None)
            return ''

        counter = cls._msg_counter.get(origin.session_id, 0) + 1
        cls._msg_counter[origin.session_id] = counter
        ext_id = f'cli:{origin.session_id}:{counter}'
        cls._last_external_id[origin.session_id] = ext_id
        return ext_id

    @classmethod
    @asynccontextmanager
    async def typing(cls, origin: CliOrigin) -> AsyncIterator[None]:
        writer = cls._writers.get(origin.session_id)
        if writer is None:
            yield
            return
        try:
            writer.write(b'{"type": "typing_on"}\n')
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            cls._writers.pop(origin.session_id, None)
            yield
            return
        try:
            yield
        finally:
            try:
                writer.write(b'{"type": "typing_off"}\n')
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                cls._writers.pop(origin.session_id, None)
