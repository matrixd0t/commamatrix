# builtin/self_extension/__init__.py

"""Self-modification tools — manage agent extensions at runtime."""

from .tools import self_extension_guide_path, list_all, manage, read_guide, self_extension_when_and_why

__all__ = [
    "self_extension_guide_path",
    "list_all",
    "manage",
    "read_guide",
    "self_extension_when_and_why",
]
