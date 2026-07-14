# builtin/codeact/__init__.py

"""CodeAct plugin — optional-by-import Python execution with virtual tool modules.

Importing this package makes CodeAct available as a AbstractService extension.
The ``CodeActManager`` is discovered automatically and managed by the
agent's service lifecycle when added via ``agent.add_extension``.
"""

from . import hooks, tools, manager

__all__ = ['hooks', 'tools', 'manager']
