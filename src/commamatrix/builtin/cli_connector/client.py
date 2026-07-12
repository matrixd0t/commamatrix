# builtin/cli_connector/client.py

"""
Автономный скрипт. НЕ импортирует ничего из основного пакета —
запускается как самостоятельный процесс через `python client.py <host> <port>`,
поэтому не зависит от окружения/venv основного приложения
"""
import asyncio
import json
import sys
import uuid
import getpass


PROMPT = '> '


async def main(host: str, port: int) -> None:
    session_id = str(uuid.uuid4())
    reader, writer = await asyncio.open_connection(host, port)
    username = getpass.getuser()
    typing_active = False
    done = False

    async def read_loop() -> None:
        nonlocal typing_active, done
        try:
            async for raw_line in reader:
                try:
                    msg = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get('type')

                if msg_type == 'shutdown':
                    print('\nСервер завершил работу.')
                    done = True
                    return

                if msg_type == 'message':
                    if typing_active:
                        _clear_line()
                        typing_active = False
                    print(f"\n{msg.get('text', '')}\n{PROMPT}", end='', flush=True)

                elif msg_type == 'image':
                    if typing_active:
                        _clear_line()
                        typing_active = False
                    data = msg.get('data', '')
                    try:
                        meta = json.loads(data)
                        ref = meta.get('ref', data)
                        mime = meta.get('mime_type', 'unknown')
                    except (json.JSONDecodeError, TypeError):
                        ref = str(data)
                        mime = 'unknown'
                    print(f"\n[Изображение] {ref} ({mime})\n{PROMPT}", end='', flush=True)

                elif msg_type == 'file':
                    if typing_active:
                        _clear_line()
                        typing_active = False
                    data = msg.get('data', '')
                    try:
                        meta = json.loads(data)
                        filename = meta.get('filename', 'unknown')
                        ref = meta.get('ref', '')
                        mime = meta.get('mime_type', 'unknown')
                    except (json.JSONDecodeError, TypeError):
                        filename = str(data)
                        ref = ''
                        mime = 'unknown'
                    location = f' ({ref})' if ref else ''
                    print(f"\n[Файл] {filename}{location} ({mime})\n{PROMPT}", end='', flush=True)

                elif msg_type == 'typing_on':
                    typing_active = True
                    print('печатает...', end='\r', flush=True)

                elif msg_type == 'typing_off':
                    if typing_active:
                        _clear_line()
                        typing_active = False
                        print(PROMPT, end='', flush=True)

        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            done = True

    def _clear_line() -> None:
        print('\r' + ' ' * 40 + '\r', end='', flush=True)

    read_task = asyncio.create_task(read_loop())

    print('Подключено. Пишите сообщения, Ctrl+C для выхода.\n')
    loop = asyncio.get_event_loop()
    try:
        while not done:
            text = await loop.run_in_executor(None, input, PROMPT)
            if not text.strip():
                continue
            payload = json.dumps({'session_id': session_id, 'username': username, 'text': text}) + '\n'
            writer.write(payload.encode())
            await writer.drain()
    except (KeyboardInterrupt, EOFError, OSError):
        pass
    finally:
        done = True
        read_task.cancel()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Использование: python client.py <host> <port>', file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(main(sys.argv[1], int(sys.argv[2])))
    except ConnectionRefusedError:
        print(f'Не удалось подключиться к {sys.argv[1]}:{sys.argv[2]} — сервер не запущен?', file=sys.stderr)
        sys.exit(1)
