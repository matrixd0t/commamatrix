# extensions/errors.py


class ExtensionError(RuntimeError):
    """Base class for extension lifecycle failures."""


class ExtensionUnavailableError(ExtensionError):
    """Raised when an extension source is currently unavailable."""


class StaleExtensionError(ExtensionError):
    """Raised when code tries to use a descriptor removed from a manager."""
