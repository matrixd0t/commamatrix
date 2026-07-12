# extensions/__init__.py

from .contracts import ExtensionDescriptor, ExtensionSource
from .errors import ExtensionError, ExtensionUnavailableError, StaleExtensionError

__all__ = [
    "ExtensionDescriptor",
    "ExtensionSource",
    "ExtensionError",
    "ExtensionUnavailableError",
    "StaleExtensionError",
]
