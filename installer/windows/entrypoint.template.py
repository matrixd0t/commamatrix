# installer/windows/entrypoint.py (generated)

from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import socket
import sys
import threading
import webbrowser
from ctypes import wintypes
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pystray
from dotenv import load_dotenv
from PIL import Image, ImageDraw

from commamatrix import Agent, agentic_model, reasoning_level
from commamatrix.builtin.http_connector import HttpConnector
from commamatrix.builtin.llm_http_adapter import (
    anthropic_api_key,
    llm_api_base,
    llm_api_protocol,
    llm_refresh_on_start,
    openai_api_key,
)
from commamatrix.components.config import log_file, log_to_console
from commamatrix.components.server import http_host, http_port
from commamatrix.utils import commamatrix_dir

API_ENV = __API_ENV__
TOKEN_ENV = __TOKEN_ENV__
TOKEN_FIELD = __TOKEN_FIELD__
PROTOCOL = __PROTOCOL__
MODEL = __MODEL__
HTTP_HOST = __HTTP_HOST__
HTTP_PORT = __HTTP_PORT__
LANGUAGE = __LANGUAGE__

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR = WORKSPACE / ".commamatrix"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "commamatrix.log"
INSTANCE_MUTEX_NAME = "Local\\CommaMatrix-" + hashlib.sha256(
    str(WORKSPACE).casefold().encode("utf-8")
).hexdigest()
_INSTANCE_MUTEX: Any = None
_INSTANCE_CLOSE_HANDLE: Any = None

EXTENSIONS = [
    "commamatrix.builtin.codeact",
    "commamatrix.builtin.http_connector",
    "commamatrix.builtin.llm_http_adapter",
    "commamatrix.builtin.mcp",
    "commamatrix.builtin.planner",
    "commamatrix.builtin.self_extension",
    "commamatrix.builtin.subagent",
    "commamatrix.builtin.web_utils",
    "commamatrix.builtin.apply_patch",
    "commamatrix.builtin.data_tools",
    "commamatrix.builtin.storage_utils",
    "commamatrix.builtin.default_instruction",
]


def _choose_port(host: str, requested: int) -> int:
    """Keep the requested port when available and otherwise ask the OS."""
    if requested == 0:
        return 0
    probe_host = "127.0.0.1" if host == "localhost" else host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((probe_host, requested))
    except OSError:
        return 0
    return requested


def _label(ru: str, en: str) -> str:
    return ru if LANGUAGE == "ru" else en


def _browser_url(url: str) -> str:
    return url.replace("://0.0.0.0:", "://127.0.0.1:", 1)


def _fallback_icon() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (35, 35, 45, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(80, 150, 255, 255))
    draw.ellipse((21, 21, 29, 29), fill=(255, 255, 255, 255))
    draw.ellipse((35, 21, 43, 29), fill=(255, 255, 255, 255))
    draw.arc((20, 22, 44, 45), start=20, end=160, fill=(255, 255, 255, 255), width=3)
    return image


def _load_icon() -> Image.Image:
    icon_path = DATA_DIR / "assets" / "logo.png"
    if icon_path.is_file():
        with Image.open(icon_path) as image:
            return image.convert("RGBA").copy()
    return _fallback_icon()


def _acquire_instance() -> bool:
    global _INSTANCE_CLOSE_HANDLE, _INSTANCE_MUTEX

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    create_mutex.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = create_mutex(None, False, INSTANCE_MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        close_handle(handle)
        return False
    _INSTANCE_MUTEX = handle
    _INSTANCE_CLOSE_HANDLE = close_handle
    return True


def _release_instance() -> None:
    global _INSTANCE_CLOSE_HANDLE, _INSTANCE_MUTEX
    if _INSTANCE_MUTEX is not None:
        _INSTANCE_CLOSE_HANDLE(_INSTANCE_MUTEX)
        _INSTANCE_MUTEX = None
        _INSTANCE_CLOSE_HANDLE = None


def _build_agent(*, initialize: bool) -> Agent:
    os.chdir(WORKSPACE)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    load_dotenv(DATA_DIR / ".env", override=True)

    config = {
        commamatrix_dir: ".commamatrix",
        llm_api_base: os.environ.get(API_ENV, ""),
        TOKEN_FIELD: os.environ.get(TOKEN_ENV, ""),
        llm_api_protocol: PROTOCOL,
        agentic_model: MODEL,
        reasoning_level: "max",
        http_host: HTTP_HOST,
        http_port: _choose_port(HTTP_HOST, HTTP_PORT),
        log_file: str(LOG_FILE),
        log_to_console: False,
    }
    if initialize:
        config[llm_refresh_on_start] = False

    return Agent("commamatrix", config=config)


async def _initialize(credentials_file: Path | None) -> None:
    agent = _build_agent(initialize=True)
    started = False
    try:
        await agent.add_extensions(*EXTENSIONS)
        await agent.start()
        started = True
        credentials: Any = None
        for connector in agent.connector_manager.resolve():
            if isinstance(connector, HttpConnector):
                credentials = connector.initial_admin_credentials
                break
        if credentials is not None and credentials_file is not None:
            credentials_file.parent.mkdir(parents=True, exist_ok=True)
            credentials_file.write_text(
                json.dumps(asdict(credentials), ensure_ascii=False),
                encoding="utf-8",
            )
    finally:
        if started:
            await agent.stop()


class _TrayRuntime:
    def __init__(self, loop: asyncio.AbstractEventLoop, commands: asyncio.Queue[str], agent: Agent) -> None:
        self._loop = loop
        self._commands = commands
        self._agent = agent
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem(_label("Открыть CommaMatrix", "Open CommaMatrix"), self._open),
            pystray.MenuItem(_label("Перезапустить", "Restart"), self._restart),
            pystray.MenuItem(_label("Открыть логи", "Open logs"), self._open_logs),
            pystray.MenuItem(_label("Закрыть", "Close"), self._close),
        )
        self._icon = pystray.Icon(
            "CommaMatrix",
            _load_icon(),
            "CommaMatrix",
            menu=menu,
        )
        self._thread = threading.Thread(target=self._icon.run, name="commamatrix-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)

    def _open(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(_browser_url(self._agent.http_server.base_url))

    def _open_logs(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        os.startfile(LOG_DIR)  # type: ignore[attr-defined]

    def _restart(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._loop.call_soon_threadsafe(self._commands.put_nowait, "restart")

    def _close(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._loop.call_soon_threadsafe(self._commands.put_nowait, "close")


async def _run_runtime() -> None:
    if not _acquire_instance():
        return

    agent = _build_agent(initialize=False)
    commands: asyncio.Queue[str] = asyncio.Queue()
    tray = _TrayRuntime(asyncio.get_running_loop(), commands, agent)
    started = False
    try:
        await agent.add_extensions(*EXTENSIONS)
        await agent.start()
        started = True
        tray.start()
        webbrowser.open(_browser_url(agent.http_server.base_url))
        command = await commands.get()
        if command == "restart":
            await agent.stop()
            started = False
            tray.stop()
            _release_instance()
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])
    finally:
        if started:
            await agent.stop()
        tray.stop()
        _release_instance()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--foreground", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.initialize:
        asyncio.run(_initialize(args.credentials_file))
    else:
        asyncio.run(_run_runtime())


if __name__ == "__main__":
    main()
