# builtin/codeact/executor/__init__.py

"""Execution backends for running CodeAct code in isolated environments."""

from .backend import ExecutionBackend, ExecutionResult
from .subprocess import SubprocessBackend
from .docker import DockerBackend
from .systemd import SystemdBackend

__all__ = [
    'ExecutionBackend', 'ExecutionResult',
    'SubprocessBackend', 'DockerBackend', 'SystemdBackend',
]
