# builtin/web_utils/security.py

"""Lightweight SSRF policy for web_utils.

No DNS lookups — checks only scheme, hostname literal, and IP representation.
"""

from __future__ import annotations

from urllib.parse import urlparse

_PRIVATE_PREFIXES_V4 = (
    "10.",
    "127.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.",
)


def _is_private_ip(host: str) -> bool:
    if ":" in host:
        return host in ("::1", "::", "[::1]", "[::]")
    return host.startswith(_PRIVATE_PREFIXES_V4)


def _is_localhost(host: str) -> bool:
    return host in ("localhost", "localhost.", "[::1]", "[::]")


def validate_url(url: str) -> None:
    """Validate url against SSRF policy.

    Raises ``ValueError`` with a human-readable message on violation.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {scheme!r}. Only http/https are allowed.")
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain credentials.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL has no hostname.")
    if _is_localhost(host) or _is_private_ip(host):
        raise ValueError(f"Access to host {host!r} is not allowed.")
