# extensions/__init__.py

from .contracts import Descriptor, Source, ExtensionError, UnavailableSourceError, StaleDescriptorError

__all__ = [
    "Descriptor",
    "Source",
    "ExtensionError",
    "UnavailableSourceError",
    "StaleDescriptorError",
]
