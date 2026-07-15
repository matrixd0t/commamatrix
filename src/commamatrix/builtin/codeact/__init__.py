# builtin/codeact/__init__.py

"""CodeAct plugin — optional-by-import Python execution with virtual tool modules.

Importing this package makes CodeAct available as a Service extension.
The ``CodeActService`` is discovered automatically and managed by the
agent's service lifecycle when added via ``agent.add_extension``.
"""

from . import hooks, tools, service

__all__ = ['hooks', 'tools', 'service.py']
