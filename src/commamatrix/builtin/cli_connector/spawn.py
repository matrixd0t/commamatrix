import platform
import shutil
import subprocess
import sys
from pathlib import Path


CLIENT_SCRIPT = Path(__file__).parent / 'client.py'


def spawn_terminal_window(host: str, port: int) -> None:
    """
    Открывает НОВОЕ окно терминала как независимый процесс ОС и запускает
    в нём client.py. Окно не привязано к процессу-родителю: закрытие
    консоли, из которой всё запускалось, или переключение фокуса на
    него никак не влияют.
    """
    system = platform.system()
    python = sys.executable
    script = str(CLIENT_SCRIPT)

    if system == 'Windows':
        subprocess.Popen(
            [python, script, host, str(port)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

    else:  # Linux
        emulator = _find_linux_terminal()
        if emulator is None:
            raise RuntimeError(
                'Не найден ни один эмулятор терминала (x-terminal-emulator, '
                'gnome-terminal, konsole, xterm). Установите один из них или '
                'запустите client.py вручную: '
                f'{python} {script} {host} {port}'
            )
        subprocess.Popen([emulator, '-e', python, script, host, str(port)])


# noinspection PyDeprecation
def _find_linux_terminal() -> str | None:
    candidates = ('x-terminal-emulator', 'gnome-terminal', 'konsole', 'xfce4-terminal', 'xterm')
    for name in candidates:
        if shutil.which(name):
            return name
    return None


def _shell_quote(value: str) -> str:
    """
    Экранирование для AppleScript-строки
    """
    return value.replace('\\', '\\\\').replace('"', '\\"')
