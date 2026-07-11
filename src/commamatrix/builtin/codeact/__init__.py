# builtin/codeact/__init__.py

"""CodeAct plugin — optional-by-import Python execution with virtual tool modules.

Importing this package activates CodeAct: registers hooks that create the
runtime on agent start and swap tool lists before each LLM call.
"""

from . import hooks, tools, runtime

__all__ = ['hooks', 'tools', 'runtime']
