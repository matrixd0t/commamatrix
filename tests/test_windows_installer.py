# tests/test_windows_installer.py

from __future__ import annotations

from pathlib import Path

from installer.windows.bootstrap import _select_data_policy, _workspace_has_data


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
