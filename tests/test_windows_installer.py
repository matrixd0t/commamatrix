# tests/test_windows_installer.py

from __future__ import annotations

from pathlib import Path

from installer.windows import bootstrap
from installer.windows.bootstrap import Provider, Selection, _select_data_policy, _workspace_has_data


def test_workspace_data_policy_keeps_existing_data(tmp_path, monkeypatch):
    data_dir = tmp_path / ".commamatrix"
    data_dir.mkdir()
    marker = data_dir / "db.sqlite"
    marker.write_text("existing", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")

    assert _workspace_has_data(tmp_path) is True
    assert _select_data_policy("en", tmp_path) is True
    assert marker.read_text(encoding="utf-8") == "existing"


def test_workspace_data_policy_clears_existing_data(tmp_path, monkeypatch):
    data_dir = tmp_path / ".commamatrix"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("existing", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    assert _select_data_policy("en", tmp_path) is False
    assert not data_dir.exists()


def test_entrypoint_checks_pypi_for_library_updates():
    template = Path(__file__).parents[1] / "installer" / "windows" / "entrypoint.template.py"
    source = template.read_text(encoding="utf-8")

    assert 'PYPI_PACKAGE_API = "https://pypi.org/pypi/commamatrix/json"' in source
    assert "package_info.get(\"version\")" in source
    assert 'INSTALLER_URL = "https://github.com/matrixd0t/commamatrix/releases/latest/download/install.ps1"' in source
    assert "GITHUB_LATEST_RELEASE_API" not in source


def test_basic_selection_uses_saved_provider_and_token(tmp_path, monkeypatch):
    data_dir = tmp_path / ".commamatrix"
    data_dir.mkdir()
    env_path = data_dir / ".env"
    env_path.write_text(
        'LLM_API_BASE="https://provider.example/v1"\n'
        'OPENAI_API_KEY="saved-token"\n',
        encoding="utf-8",
    )
    provider = Provider(
        provider_id="saved",
        display_name="Saved provider",
        api_base="https://provider.example/v1",
        api_env="LLM_API_BASE",
        token_env="OPENAI_API_KEY",
        protocol="chat_completions",
        recommended_model="saved-model",
        instructions=(),
        is_default=True,
    )
    monkeypatch.setattr(bootstrap, "DEFAULT_WORKSPACE", tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")

    selection = bootstrap._basic_selection("en", [provider])

    assert selection.api_base == "https://provider.example/v1"
    assert selection.token == "saved-token"
    assert env_path.read_text(encoding="utf-8") == (
        'LLM_API_BASE="https://provider.example/v1"\n'
        'OPENAI_API_KEY="saved-token"\n'
    )


def test_write_env_does_not_rewrite_saved_configuration(tmp_path):
    data_dir = tmp_path / ".commamatrix"
    data_dir.mkdir()
    env_path = data_dir / ".env"
    original = '# user formatting\nLLM_API_BASE="https://provider.example/v1"\nOPENAI_API_KEY="saved-token"\n'
    env_path.write_text(original, encoding="utf-8")
    selection = Selection(
        workspace=tmp_path,
        api_base="https://provider.example/v1",
        api_env="LLM_API_BASE",
        token_env="OPENAI_API_KEY",
        protocol="chat_completions",
        model="saved-model",
        host="127.0.0.1",
        port=8338,
        token="saved-token",
        preserve_data=True,
    )

    bootstrap._write_env(selection)

    assert env_path.read_text(encoding="utf-8") == original
