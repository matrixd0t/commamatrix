# core/base/descriptor.py

from __future__ import annotations

import hashlib
import json
import weakref
from dataclasses import dataclass, field
from typing import Any


class StaleDescriptorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Descriptor:
    """Immutable, source-independent description."""

    id: str
    _source_ref: weakref.ReferenceType = field(repr=False)

    @property
    def fingerprint(self) -> str:
        """Return a deterministic hash of the descriptor's semantic content."""
        encoded = json.dumps(
            self._fingerprint_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {"id": self.id}
