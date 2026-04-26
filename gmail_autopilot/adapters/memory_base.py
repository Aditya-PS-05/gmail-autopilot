"""Optional contact-memory hook.

This is the brace-shaped extension point. With brace's contact graph plugged in,
each per-email pipeline gains relationship context (last interaction, recent
signals, prior thread summary), and signal-scoring + draft-generation become
network-aware. With NullMemoryProvider, lookups return None and the workflow
runs as a generic responder."""

from __future__ import annotations

from typing import Protocol

from ..models import ContactMemory


class MemoryProvider(Protocol):
    def lookup(self, contact_email: str) -> ContactMemory | None: ...
