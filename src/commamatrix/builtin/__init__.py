# builtin/__init__.py

"""
This is a package containing some built-in 'plugins' providing basic yet essential functionality.
Also, these are perfect examples of how to design your custom logic with powerful commamatrix hooks API.
"""
from . import cli_connector
from . import sql
from . import sqlite
from . import fs
from . import python
from . import example_tools

__all__ = [
    'cli_connector',
    'sql',
    'sqlite',
    'fs',
    'python',
    'example_tools',
]
