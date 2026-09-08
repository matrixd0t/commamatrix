# tests/test_plugin_dependencies.py

from __future__ import annotations

import commamatrix.core.extensions as extensions_module
from commamatrix.core.extensions import missing_plugin_dependencies


def test_reports_missing_third_party_imports(tmp_path):
    plugin = tmp_path / "scholarhub.py"
    plugin.write_text(
        "\n".join([
            "import os",
            "import pytest",
            "import missing_one",
            "import missing_one.submodule",
            "import missing_two.mod",
            "from missing_three import thing",
            "from . import internal",
            "import importlib",
            "",
            "importlib.import_module('dynamically_missing')",
        ]),
        encoding="utf-8",
    )

    assert missing_plugin_dependencies([plugin]) == [
        "missing_one",
        "missing_three",
        "missing_two",
    ]


def test_excludes_sibling_plugin_modules(tmp_path):
    (tmp_path / "first.py").write_text("import second\n", encoding="utf-8")
    (tmp_path / "second.py").write_text("import missing_one\n", encoding="utf-8")

    assert missing_plugin_dependencies([tmp_path / "first.py", tmp_path / "second.py"]) == [
        "missing_one"
    ]


def test_package_targets_scan_nested_modules(tmp_path):
    package = tmp_path / "scholarhub"
    package.mkdir()
    (package / "__init__.py").write_text("import missing_one\n", encoding="utf-8")
    (package / "tools.py").write_text("import missing_two\n", encoding="utf-8")

    assert missing_plugin_dependencies([package]) == ["missing_one", "missing_two"]


def test_maps_known_import_aliases(tmp_path, monkeypatch):
    plugin = tmp_path / "imaging.py"
    plugin.write_text("import PIL\n", encoding="utf-8")
    monkeypatch.setattr(extensions_module.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(extensions_module, "packages_distributions", lambda: {"PIL": ["Wrong-Dist"]})

    assert missing_plugin_dependencies([plugin]) == ["Pillow"]
