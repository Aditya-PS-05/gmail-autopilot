from __future__ import annotations

from ..models import ContactMemory


class NullMemoryProvider:
    """Default memory provider. Returns None for every lookup."""

    def lookup(self, contact_email: str) -> ContactMemory | None:
        return None
