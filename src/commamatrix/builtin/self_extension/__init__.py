# builtin/self_extension/__init__.py

"""Self-modification tools — manage agent extensions at runtime."""

from .tools import list_all, manage, readme, self_extension_when_and_why

__all__ = [
    "list_all", "manage", "readme", "self_extension_when_and_why"
]
