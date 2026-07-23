# builtin/self_modif/__init__.py

"""Self-modification tools — manage agent extensions at runtime."""

from .tools import add_extension, list_extensions, reload_extension, remove_extension, read_guide

__all__ = [
    "add_extension", "reload_extension", "remove_extension", "list_extensions", "read_guide"
]
