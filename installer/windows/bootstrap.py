# installer/windows/bootstrap.py

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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


def _text(language: str, ru: str, en: str) -> str:
    return ru if language == "ru" else en


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
        if not isinstance(raw_instructions, (list, tuple)):
            raw_instructions = ()
        providers.append(
            Provider(
                provider_id=str(provider_id),
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
    raise InstallerError("The choice prompt did not return a value")


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
        token = input(_text(language, "Токен доступа: ", "Access token: ")).strip()
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
    model = provider.recommended_model
    if not model:
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
        model=model,
        host="127.0.0.1",
        port=8338,
        token=token,
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
            if isinstance(value, BackRequested):
                raise InstallerError(_text(language, "Установка отменена.", "Installation cancelled."))
            state["workspace"] = Path(os.path.expandvars(os.path.expanduser(value))).resolve()
            stage = 1
            continue

        if stage == 1:
            names = [
                provider.display_name + (
                    _text(language, " (рекомендуется)", " (recommended)") if provider.is_default else ""
                )
                for provider in providers
            ]
            names.append(_text(language, "Собственный провайдер", "Custom provider"))
            selected = _prompt_choice(
                language,
                _text(language, "Выберите провайдера:", "Select a provider:"),
                names,
            )
            if type(selected) is not int:
                if isinstance(selected, BackRequested):
                    stage = 0
                    continue
                raise InstallerError("Provider choice was not a number")
            if selected == len(providers):
                state["custom"] = True
                stage = 2
            else:
                provider = providers[cast(int, selected)]
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
            if isinstance(selected, BackRequested):
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
            if isinstance(value, BackRequested):
                stage = 2
                continue
            state["api_base"] = value
            stage = 3
            continue

        if stage == 3:
            state["token"] = _prompt_token(language)
            stage = 4
            continue

        if stage == 4:
            default_model = state.get("model")
            model_prompt = _text(language, "Имя модели", "Model name")
            if default_model:
                model_prompt += _text(language, " (рекомендуется)", " (recommended)")
            value = _prompt_text(language, model_prompt, default=default_model)
            if isinstance(value, BackRequested):
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
            if isinstance(host_choice, BackRequested):
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
            if isinstance(value, BackRequested):
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
            )

    raise InstallerError("The advanced configuration prompt did not return a value")


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


def _generate_entrypoint(template: Path, workspace: Path, selection: Selection, language: str, venv: Path) -> Path:
    try:
        source = template.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallerError(f"Could not read entrypoint template: {exc}") from exc

    replacements = {
        "__API_ENV__": json.dumps(selection.api_env),
        "__TOKEN_ENV__": json.dumps(selection.token_env),
        "__TOKEN_FIELD__": "anthropic_api_key" if selection.token_env == "ANTHROPIC_API_KEY" else "openai_api_key",
        "__PROTOCOL__": json.dumps(selection.protocol),
        "__MODEL__": json.dumps(selection.model),
        "__HTTP_HOST__": json.dumps(selection.host),
        "__HTTP_PORT__": str(selection.port),
        "__LANGUAGE__": json.dumps(language),
        "__VENV_SITE_PACKAGES__": json.dumps(str((venv / "Lib" / "site-packages").resolve())),
    }
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    if any(marker in source for marker in replacements):
        raise InstallerError("Entrypoint template contains unreplaced markers")

    workspace.mkdir(parents=True, exist_ok=True)
    entrypoint = workspace / "entrypoint.py"
    entrypoint.write_text(source, encoding="utf-8")
    return entrypoint


def _venv_python(venv: Path) -> Path:
    candidates = (
        venv / "Scripts" / "python.exe",
        venv / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise InstallerError(f"An existing Python virtual environment was not found: {venv}")


def _parse_args() -> argparse.Namespace:
    installer_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", type=Path, default=installer_root / "providers.json")
    parser.add_argument("--template", type=Path, default=installer_root / "entrypoint.template.py")
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--result-file", type=Path)
    return parser.parse_args()


def main() -> int:
    language = "ru"
    try:
        args = _parse_args()
        language = _select_language()
        providers = _parse_providers(args.providers.resolve(), language)
        mode = _select_mode(language)
        selection = _basic_selection(language, providers) if mode == "basic" else _advanced_selection(language, providers)
        _write_env(selection)
        entrypoint = _generate_entrypoint(args.template.resolve(), selection.workspace, selection, language, args.venv.resolve())
        if args.result_file is not None:
            try:
                result_file = args.result_file.resolve()
                result_file.parent.mkdir(parents=True, exist_ok=True)
                result_file.write_text(str(entrypoint.resolve()), encoding="utf-8")
            except OSError as exc:
                raise InstallerError(f"Could not write bootstrap result: {exc}") from exc
        print()
        print(
            _text(
                language,
                f"Entrypoint создан: {entrypoint}",
                f"Entrypoint created: {entrypoint}",
            )
        )
        return 0
    except (KeyboardInterrupt, EOFError):
        print(_text(language, "Установка отменена.", "Installation cancelled."))
        return 1
    except InstallerError as exc:
        print(_text(language, f"Ошибка настройки: {exc}", f"Configuration error: {exc}"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
