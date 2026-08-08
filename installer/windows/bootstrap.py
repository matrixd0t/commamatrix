# installer/windows/bootstrap.py

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = "matrixd0t/commamatrix"
DEFAULT_VERSION = "0.1.9"
DEFAULT_WORKSPACE = Path.home() / "commamatrix"
PROTOCOLS = (
    ("chat_completions", "Chat Completions"),
    ("responses", "Responses"),
    ("anthropic_messages", "Anthropic Messages"),
)


class InstallerError(RuntimeError):
    pass


class BackRequested:
    pass


BACK = BackRequested()


@dataclass(frozen=True, slots=True)
class Provider:
    provider_id: str
    display_name: str
    api_base: str
    api_env: str
    token_env: str
    protocol: str
    recommended_model: str | None
    instructions: tuple[str, ...]
    is_default: bool


@dataclass(frozen=True, slots=True)
class Selection:
    workspace: Path
    api_base: str
    api_env: str
    token_env: str
    protocol: str
    model: str
    host: str
    port: int
    token: str
    autostart: bool
    provider_name: str


@dataclass(frozen=True, slots=True)
class Resources:
    python_version: str
    providers: Path
    entrypoint_template: Path
    runtime_requirements: Path
    icon: Path | None
    wheel: Path | None
    shortcut_icon: Path | None = None


def _read_manifest(path: Path, version: str) -> dict[str, str]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallerError(f"Could not read release manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != version:
        raise InstallerError("Release manifest version does not match the installer version")
    result: dict[str, str] = {}
    for key in ("python", "wheel", "providers", "entrypoint_template", "runtime_requirements", "icon", "shortcut_icon"):
        value = manifest.get(key)
        if not isinstance(value, str):
            continue
        value_path = Path(value)
        if key in {"icon", "shortcut_icon"}:
            if len(value_path.parts) == 2 and value_path.parts[0] == "assets":
                result[key] = value
        elif value_path.name == value:
            result[key] = value
    required = ("python", "wheel", "providers", "entrypoint_template", "runtime_requirements", "icon", "shortcut_icon")
    if any(key not in result for key in required):
        raise InstallerError("Release manifest is missing required assets")
    return result


def _text(language: str, ru: str, en: str) -> str:
    return ru if language == "ru" else en


def _run_quiet(command: list[str | Path], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode == 0:
        return
    details = (result.stderr or result.stdout).strip()
    if len(details) > 2000:
        details = details[-2000:]
    raise InstallerError(details or f"Command failed with exit code {result.returncode}")


def _find_managed_python(uv: str, version: str) -> Path:
    result = subprocess.run(
        [uv, "python", "find", "--no-project", "--managed-python", version],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        if len(details) > 2000:
            details = details[-2000:]
        raise InstallerError(details or f"Command failed with exit code {result.returncode}")
    python = Path(result.stdout.strip())
    if not python.is_file():
        raise InstallerError(f"Managed Python was not found: {python}")
    return python


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "CommaMatrix-installer"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def _load_resources(
    *,
    repository: str,
    version: str,
    source_root: Path | None,
    temporary: Path,
) -> Resources:
    if source_root is not None:
        installer_root = source_root / "installer" / "windows"
        manifest = _read_manifest(installer_root / "manifest.json", version)
        providers = installer_root / manifest["providers"]
        entrypoint_template = installer_root / manifest["entrypoint_template"]
        runtime_requirements = installer_root / manifest["runtime_requirements"]
        icon_source = source_root / manifest["icon"]
        shortcut_icon_source = source_root / manifest["shortcut_icon"]
        icon = temporary / "logo.png"
        shortcut_icon = temporary / "logo.ico"
        for source, destination in ((icon_source, icon), (shortcut_icon_source, shortcut_icon)):
            if not source.is_file():
                raise InstallerError(f"Installer asset is missing: {source}")
            shutil.copy2(source, destination)
        return Resources(manifest["python"], providers, entrypoint_template, runtime_requirements, icon, None, shortcut_icon)

    tag = f"v{version}"
    raw_base = f"https://raw.githubusercontent.com/{repository}/{tag}/installer/windows"
    raw_root = f"https://raw.githubusercontent.com/{repository}/{tag}"
    manifest_path = temporary / "manifest.json"
    _download(f"{raw_base}/manifest.json", manifest_path)
    manifest = _read_manifest(manifest_path, version)
    providers = temporary / manifest["providers"]
    entrypoint_template = temporary / manifest["entrypoint_template"]
    runtime_requirements = temporary / manifest["runtime_requirements"]
    _download(f"{raw_base}/{manifest['providers']}", providers)
    _download(f"{raw_base}/{manifest['entrypoint_template']}", entrypoint_template)
    _download(f"{raw_base}/{manifest['runtime_requirements']}", runtime_requirements)

    icon = temporary / "logo.png"
    shortcut_icon = temporary / "logo.ico"
    _download(f"{raw_root}/{manifest['icon']}", icon)
    _download(f"{raw_root}/{manifest['shortcut_icon']}", shortcut_icon)

    wheel = temporary / manifest["wheel"]
    release_url = f"https://github.com/{repository}/releases/download/{tag}/{wheel.name}"
    _download(release_url, wheel)
    return Resources(manifest["python"], providers, entrypoint_template, runtime_requirements, icon, wheel, shortcut_icon)


def _parse_providers(path: Path, language: str) -> list[Provider]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallerError(f"Could not read providers.json: {exc}") from exc
    raw_providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(raw_providers, list):
        raise InstallerError("providers.json must contain a providers list")

    providers: list[Provider] = []
    for raw in raw_providers:
        if not isinstance(raw, dict):
            continue
        names = raw.get("display_name", {})
        instructions = raw.get("instructions", {})
        provider_id = raw.get("id")
        api_base = raw.get("api_base")
        api_env = raw.get("api_env", "LLM_API_BASE")
        token_env = raw.get("token_env")
        protocol = raw.get("protocol", "chat_completions")
        if not all(isinstance(value, str) and value.strip() for value in (provider_id, api_base, api_env, token_env, protocol)):
            continue
        name = names.get(language, names.get("en", provider_id)) if isinstance(names, dict) else provider_id
        raw_instructions = instructions.get(language, instructions.get("en", ())) if isinstance(instructions, dict) else ()
        if isinstance(raw_instructions, str):
            raw_instructions = [raw_instructions]
        providers.append(
            Provider(
                provider_id=provider_id,
                display_name=str(name),
                api_base=api_base.strip(),
                api_env=api_env.strip(),
                token_env=token_env.strip(),
                protocol=protocol.strip(),
                recommended_model=(
                    raw.get("recommended_model").strip()
                    if isinstance(raw.get("recommended_model"), str) and raw.get("recommended_model").strip()
                    else None
                ),
                instructions=tuple(str(line) for line in raw_instructions if str(line).strip()),
                is_default=bool(raw.get("default", False)),
            )
        )
    return providers


def _prompt_choice(language: str, title: str, options: list[str], *, back: bool = True) -> int | BackRequested:
    print(title)
    for index, option in enumerate(options, 1):
        print(f"{index}. {option}")
    if back:
        print(_text(language, "0. Назад", "0. Back"))
    while True:
        value = input("> ").strip()
        if back and value == "0":
            return BACK
        try:
            selected = int(value)
        except ValueError:
            print(_text(language, "Введите номер пункта.", "Enter an option number."))
            continue
        if 1 <= selected <= len(options):
            return selected - 1
        print(_text(language, "Введите номер пункта.", "Enter an option number."))


def _prompt_text(
    language: str,
    prompt: str,
    *,
    default: str | None = None,
    back: bool = True,
) -> str | BackRequested:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if back and value == "0":
            return BACK
        if not value and default is not None:
            return default
        if value:
            return value
        print(_text(language, "Значение не может быть пустым.", "The value must not be empty."))


def _prompt_token(language: str) -> str:
    while True:
        token = getpass.getpass(_text(language, "Токен доступа: ", "Access token: ")).strip()
        if token:
            return token
        print(_text(language, "Токен не может быть пустым.", "The token must not be empty."))


def _select_language() -> str:
    print("Выберите язык / Select language:")
    print("1. Русский (рекомендуется)")
    print("2. English")
    while True:
        choice = input("> ").strip()
        if choice == "" or choice == "1":
            return "ru"
        if choice == "2":
            return "en"
        print("Введите 1 или 2 / Enter 1 or 2.")


def _select_mode(language: str) -> str:
    result = _prompt_choice(
        language,
        _text(language, "Выберите режим установки:", "Select installation mode:"),
        [
            _text(language, "Базовый (рекомендуется)", "Basic (recommended)"),
            _text(language, "Продвинутый", "Advanced"),
        ],
        back=False,
    )
    if isinstance(result, BackRequested):
        raise InstallerError("Installation mode was not selected")
    return "basic" if result == 0 else "advanced"


def _print_instructions(language: str, provider: Provider) -> None:
    if provider.display_name:
        print(provider.display_name)
    if provider.recommended_model:
        print(_text(language, f"Рекомендуемая модель: {provider.recommended_model}", f"Recommended model: {provider.recommended_model}"))
    if provider.instructions:
        print()
        for index, line in enumerate(provider.instructions):
            if index:
                print()
            print(line)
        print()


def _basic_selection(language: str, providers: list[Provider]) -> Selection:
    defaults = [provider for provider in providers if provider.is_default]
    if len(defaults) != 1:
        raise InstallerError(
            _text(
                language,
                "В providers.json должен быть ровно один провайдер по умолчанию.",
                "providers.json must contain exactly one default provider.",
            )
        )
    provider = defaults[0]
    if not provider.recommended_model:
        raise InstallerError(
            _text(
                language,
                "У провайдера по умолчанию не указана рекомендуемая модель.",
                "The default provider has no recommended model.",
            )
        )
    _print_instructions(language, provider)
    token = _prompt_token(language)
    return Selection(
        workspace=DEFAULT_WORKSPACE,
        api_base=provider.api_base,
        api_env=provider.api_env,
        token_env=provider.token_env,
        protocol=provider.protocol,
        model=provider.recommended_model,
        host="127.0.0.1",
        port=8338,
        token=token,
        autostart=False,
        provider_name=provider.display_name,
    )


def _advanced_selection(language: str, providers: list[Provider]) -> Selection:
    state: dict[str, Any] = {}
    stage = 0
    while True:
        if stage == 0:
            value = _prompt_text(
                language,
                _text(language, "Рабочий каталог", "Workspace directory"),
                default=str(DEFAULT_WORKSPACE),
            )
            if value is BACK:
                raise InstallerError(_text(language, "Установка отменена.", "Installation cancelled."))
            state["workspace"] = Path(os.path.expandvars(os.path.expanduser(value))).resolve()
            stage = 1
            continue

        if stage == 1:
            names = [
                provider.display_name + (
                    _text(language, " (рекомендуется)", " (recommended)")
                    if provider.is_default
                    else ""
                )
                for provider in providers
            ]
            names.append(_text(language, "Собственный провайдер", "Custom provider"))
            selected = _prompt_choice(
                language,
                _text(language, "Выберите провайдера:", "Select a provider:"),
                names,
            )
            if selected is BACK:
                stage = 0
                continue
            if selected == len(providers):
                state["custom"] = True
                stage = 2
            else:
                provider = providers[selected]
                state.update(
                    provider=provider,
                    custom=False,
                    api_base=provider.api_base,
                    api_env=provider.api_env,
                    token_env=provider.token_env,
                    protocol=provider.protocol,
                    model=provider.recommended_model,
                )
                _print_instructions(language, provider)
                stage = 3
            continue

        if stage == 2:
            protocols = [
                _text(language, "Chat Completions", "Chat Completions"),
                _text(language, "Responses", "Responses"),
                _text(language, "Anthropic Messages", "Anthropic Messages"),
            ]
            selected = _prompt_choice(
                language,
                _text(language, "Выберите протокол:", "Select a protocol:"),
                protocols,
            )
            if selected is BACK:
                stage = 1
                continue
            protocol = PROTOCOLS[selected][0]
            state.update(
                api_env="LLM_API_BASE",
                token_env="ANTHROPIC_API_KEY" if protocol == "anthropic_messages" else "OPENAI_API_KEY",
                protocol=protocol,
            )
            stage = 2.5
            continue

        if stage == 2.5:
            value = _prompt_text(
                language,
                _text(language, "API base (например, https://provider.example/v1)", "API base (for example, https://provider.example/v1)"),
            )
            if value is BACK:
                stage = 2
                continue
            state["api_base"] = value
            stage = 3
            continue

        if stage == 3:
            token = _prompt_token(language)
            state["token"] = token
            stage = 4
            continue

        if stage == 4:
            default_model = state.get("model")
            model_prompt = _text(language, "Имя модели", "Model name")
            if default_model:
                model_prompt += _text(language, " (рекомендуется)", " (recommended)")
            value = _prompt_text(language, model_prompt, default=default_model)
            if value is BACK:
                stage = 3
                continue
            state["model"] = value
            stage = 5
            continue

        if stage == 5:
            host_choice = _prompt_choice(
                language,
                _text(language, "Адрес HTTP-сервера:", "HTTP server address:"),
                [
                    _text(language, "127.0.0.1 (рекомендуется)", "127.0.0.1 (recommended)"),
                    "0.0.0.0",
                ],
            )
            if host_choice is BACK:
                stage = 4
                continue
            state["host"] = "127.0.0.1" if host_choice == 0 else "0.0.0.0"
            stage = 6
            continue

        if stage == 6:
            value = _prompt_text(
                language,
                _text(language, "HTTP-порт", "HTTP port"),
                default="8338",
            )
            if value is BACK:
                stage = 5
                continue
            try:
                port = int(value)
            except ValueError:
                print(_text(language, "Порт должен быть числом.", "Port must be a number."))
                continue
            if not 1 <= port <= 65535:
                print(_text(language, "Порт должен быть от 1 до 65535.", "Port must be between 1 and 65535."))
                continue
            state["port"] = port
            stage = 7
            continue

        autostart_choice = _prompt_choice(
            language,
            _text(language, "Запускать приложение при входе в Windows?", "Start the application when Windows starts?"),
            [
                _text(language, "Нет (рекомендуется)", "No (recommended)"),
                _text(language, "Да", "Yes"),
            ],
        )
        if autostart_choice is BACK:
            stage = 6
            continue
        state["autostart"] = autostart_choice == 1
        return Selection(
            workspace=state["workspace"],
            api_base=state["api_base"],
            api_env=state["api_env"],
            token_env=state["token_env"],
            protocol=state["protocol"],
            model=state["model"],
            host=state["host"],
            port=state["port"],
            token=state["token"],
            autostart=state["autostart"],
            provider_name=state.get("provider", "Custom provider").display_name if not state.get("custom") else _text(language, "Собственный провайдер", "Custom provider"),
        )


def _write_env(selection: Selection) -> None:
    if "\n" in selection.token or "\r" in selection.token:
        raise InstallerError("Token contains a newline")
    if "\n" in selection.api_base or "\r" in selection.api_base:
        raise InstallerError("API base contains a newline")
    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    path = selection.workspace / ".commamatrix" / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{selection.api_env}={quote(selection.api_base)}\n"
        f"{selection.token_env}={quote(selection.token)}\n",
        encoding="utf-8",
    )


def _generate_entrypoint(template: Path, workspace: Path, selection: Selection, language: str) -> Path:
    source = template.read_text(encoding="utf-8")
    replacements = {
        "__API_ENV__": json.dumps(selection.api_env),
        "__TOKEN_ENV__": json.dumps(selection.token_env),
        "__TOKEN_FIELD__": "anthropic_api_key" if selection.token_env == "ANTHROPIC_API_KEY" else "openai_api_key",
        "__PROTOCOL__": json.dumps(selection.protocol),
        "__MODEL__": json.dumps(selection.model),
        "__HTTP_HOST__": json.dumps(selection.host),
        "__HTTP_PORT__": str(selection.port),
        "__LANGUAGE__": json.dumps(language),
    }
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    workspace.mkdir(parents=True, exist_ok=True)
    entrypoint = workspace / "entrypoint.py"
    entrypoint.write_text(source, encoding="utf-8")
    return entrypoint


def _create_shortcut(shortcut: Path, target: Path, arguments: str, working_directory: Path, icon: Path | None) -> None:
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "CM_SHORTCUT": str(shortcut),
            "CM_TARGET": str(target),
            "CM_ARGUMENTS": arguments,
            "CM_WORKDIR": str(working_directory),
            "CM_ICON": str(icon or target),
        }
    )
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$shortcut = $shell.CreateShortcut($env:CM_SHORTCUT); "
        "$shortcut.TargetPath = $env:CM_TARGET; "
        "$shortcut.Arguments = $env:CM_ARGUMENTS; "
        "$shortcut.WorkingDirectory = $env:CM_WORKDIR; "
        "$shortcut.IconLocation = $env:CM_ICON; "
        "$shortcut.Save()"
    )
    _run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=environment)


def _add_to_user_path(path: Path) -> None:
    environment = os.environ.copy()
    environment["CM_PATH_ENTRY"] = str(path)
    script = (
        "$entry = $env:CM_PATH_ENTRY; "
        "$current = [Environment]::GetEnvironmentVariable('Path', 'User'); "
        "$parts = @($current -split ';' | Where-Object { $_ }); "
        "if ($parts -notcontains $entry) { "
        "$updated = (($parts + $entry) -join ';'); "
        "[Environment]::SetEnvironmentVariable('Path', $updated, 'User')"
        "}"
    )
    _run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=environment)


def _create_command(workspace: Path) -> Path:
    bin_dir = workspace / ".commamatrix" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    command = bin_dir / "commamatrix.cmd"
    command.write_text(
        "@echo off\n"
        f'start "" /b "{workspace / ".venv" / "Scripts" / "pythonw.exe"}" "{workspace / "entrypoint.py"}" %*\n',
        encoding="utf-8",
    )
    _add_to_user_path(bin_dir)
    return command


def _install_runtime(uv: str, workspace: Path, resources: Resources, source_root: Path | None) -> Path:
    venv = workspace / ".venv"
    workspace.mkdir(parents=True, exist_ok=True)
    _run_quiet([uv, "python", "install", resources.python_version])
    base_python = _find_managed_python(uv, resources.python_version)
    _run_quiet([base_python, "-m", "venv", "--clear", "--without-pip", venv])
    python = venv / "Scripts" / "python.exe"
    if source_root is not None:
        package_spec = ".[all]"
        _run_quiet([uv, "pip", "install", "--python", python, package_spec], cwd=source_root)
    else:
        if resources.wheel is None:
            raise InstallerError("Release wheel is missing")
        _run_quiet([uv, "pip", "install", "--python", python, f"{resources.wheel}[all]"])
    _run_quiet([uv, "pip", "install", "--python", python, "-r", resources.runtime_requirements])
    return python


def _start_background(pythonw: Path, entrypoint: Path, workspace: Path) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        [str(pythonw), str(entrypoint)],
        cwd=str(workspace),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def _final_message(language: str, credentials: dict[str, Any] | None) -> None:
    print()
    print("=" * 60)
    if credentials:
        print(_text(language, "ВАЖНО: сохраните данные администратора", "IMPORTANT: save the administrator credentials"))
        print(_text(language, f"Логин: {credentials['username']}", f"Login: {credentials['username']}"))
        print(_text(language, f"Пароль: {credentials['password']}", f"Password: {credentials['password']}"))
        print()
    print(_text(language, "Ярлык добавлен на рабочий стол.", "A shortcut has been added to the desktop."))
    print(_text(language, "Программа запущена и появилась в области уведомлений.", "The application is running in the system tray."))
    print(_text(language, "Нажмите Enter, чтобы закрыть это окно.", "Press Enter to close this window."))
    print("=" * 60)


def _install(language: str, selection: Selection, resources: Resources, uv: str, source_root: Path | None) -> None:
    workspace = selection.workspace
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".commamatrix").mkdir(parents=True, exist_ok=True)
    _write_env(selection)
    python = _install_runtime(uv, workspace, resources, source_root)
    entrypoint = _generate_entrypoint(resources.entrypoint_template, workspace, selection, language)
    if resources.icon is None or resources.shortcut_icon is None:
        raise InstallerError("Installer icons are missing")
    assets = workspace / ".commamatrix" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resources.icon, assets / "logo.png")
    shutil.copy2(resources.shortcut_icon, assets / "logo.ico")
    _create_command(workspace)
    pythonw = python.parent / "pythonw.exe"
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        desktop = Path.home()
    shortcut = desktop / "CommaMatrix.lnk"
    shortcut_icon = assets / "logo.ico"
    _create_shortcut(shortcut, pythonw, f'"{entrypoint}"', workspace, shortcut_icon)
    if selection.autostart:
        startup = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        _create_shortcut(startup / "CommaMatrix.lnk", pythonw, f'"{entrypoint}"', workspace, shortcut_icon)

    credentials_path = Path(tempfile.gettempdir()) / f"commamatrix-credentials-{os.getpid()}.json"
    try:
        _run_quiet([python, entrypoint, "--initialize", "--credentials-file", credentials_path], cwd=workspace)
        credentials = None
        if credentials_path.is_file():
            credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        _start_background(pythonw, entrypoint, workspace)
    finally:
        credentials_path.unlink(missing_ok=True)
    _final_message(language, credentials)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--uv")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    language = "ru"
    try:
        language = _select_language()
        mode = _select_mode(language)
        uv = args.uv or shutil.which("uv")
        if not uv:
            raise InstallerError("uv was not found after installation")
        source_root = args.source_root.resolve() if args.source_root else None
        with tempfile.TemporaryDirectory(prefix="commamatrix-installer-") as temporary_name:
            temporary = Path(temporary_name)
            resources = _load_resources(
                repository=args.repository,
                version=args.version,
                source_root=source_root,
                temporary=temporary,
            )
            providers = _parse_providers(resources.providers, language)
            selection = _basic_selection(language, providers) if mode == "basic" else _advanced_selection(language, providers)
            _install(language, selection, resources, uv, source_root)
        return 0
    except (KeyboardInterrupt, EOFError):
        print(_text(language, "Установка отменена.", "Installation cancelled."))
        return 1
    except InstallerError as exc:
        print(_text(language, f"Ошибка установки: {exc}", f"Installation error: {exc}"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
