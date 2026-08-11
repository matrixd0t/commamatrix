# tests/test_version.py

from importlib.metadata import version as distribution_version
from pathlib import Path
import tomllib

import commamatrix


def test_package_version_matches_project_metadata():
    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as pyproject:
        project_version = tomllib.load(pyproject)["project"]["version"]

    assert commamatrix.__version__ == project_version
    assert commamatrix.__version__ == distribution_version("commamatrix")
