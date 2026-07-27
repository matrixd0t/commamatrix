# builtin/self_modif/__init__.py

"""Self-modification tools — manage agent extensions at runtime."""

from .tools import list_extensions, manage_extension, read_guide

__all__ = [
    "list_extensions", "manage_extension", "read_guide"
]
