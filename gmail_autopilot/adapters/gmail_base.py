"""The Gmail boundary. Every Gmail interaction in the codebase goes through this Protocol.

If a future module starts importing googleapiclient directly, that's a boundary leak.
The two implementations (mock + real) are interchangeable to the engine and tools."""

from __future__ import annotations

from typing import Protocol

from ..models import CreatedDraft, Email, EmailSummary, Thread


class GmailClient(Protocol):
    def list_recent_emails(self, limit: int) -> list[EmailSummary]: ...

    def read_email(self, message_id: str) -> Email: ...

    def read_thread(self, thread_id: str) -> Thread: ...

    def create_draft(self, thread_id: str, subject: str, body: str) -> CreatedDraft: ...

    def update_draft(self, draft_id: str, subject: str, body: str) -> CreatedDraft: ...
