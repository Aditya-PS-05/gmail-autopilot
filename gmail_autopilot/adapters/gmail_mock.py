"""In-memory Gmail client backed by a JSON fixture. Used for tests and local demos."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ..errors import PermanentError
from ..models import Contact, CreatedDraft, Email, EmailSummary, Thread

_DEFAULT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "mock_inbox.json"


class MockGmailClient:
    """Failure injection lets tests simulate API errors without monkey-patching:

    client.fail_on_next_call("read_thread", TransientError("timeout"))
    """

    def __init__(
        self,
        fixture_path: Path | None = None,
        fixtures: dict | None = None,
    ):
        if fixtures is None:
            fixtures = json.loads((fixture_path or _DEFAULT_FIXTURE).read_text())
        self._emails: dict[str, dict] = {e["id"]: e for e in fixtures["emails"]}
        self._threads: dict[str, dict] = {t["id"]: t for t in fixtures["threads"]}
        self._drafts: dict[str, dict] = {}
        self._draft_counter = 0
        self._failures: list[dict] = []

    def fail_on_next_call(self, operation: str, error: Exception) -> None:
        self._failures.append({"op": operation, "error": error})

    def _maybe_fail(self, operation: str) -> None:
        for i, f in enumerate(self._failures):
            if f["op"] == operation:
                err = f["error"]
                self._failures.pop(i)
                raise err

    def list_recent_emails(self, limit: int) -> list[EmailSummary]:
        self._maybe_fail("list_recent_emails")
        ordered = sorted(self._emails.values(), key=lambda e: e["received_at"], reverse=True)
        return [
            EmailSummary(
                id=e["id"],
                thread_id=e["thread_id"],
                sender=Contact(**e["sender"]),
                subject=e["subject"],
                snippet=e["body"][:120],
                received_at=datetime.fromisoformat(e["received_at"]),
            )
            for e in ordered[:limit]
        ]

    def read_email(self, message_id: str) -> Email:
        self._maybe_fail("read_email")
        if message_id not in self._emails:
            raise PermanentError(f"email not found: {message_id}")
        e = self._emails[message_id]
        return Email(
            id=e["id"],
            thread_id=e["thread_id"],
            sender=Contact(**e["sender"]),
            recipients=[Contact(**r) for r in e.get("recipients", [])],
            subject=e["subject"],
            body=e["body"],
            received_at=datetime.fromisoformat(e["received_at"]),
        )

    def read_thread(self, thread_id: str) -> Thread:
        self._maybe_fail("read_thread")
        if thread_id not in self._threads:
            raise PermanentError(f"thread not found: {thread_id}")
        t = self._threads[thread_id]
        msgs = [self.read_email(mid) for mid in t["message_ids"]]
        return Thread(id=thread_id, messages=msgs)

    def create_draft(self, thread_id: str, subject: str, body: str) -> CreatedDraft:
        self._maybe_fail("create_draft")
        self._draft_counter += 1
        draft_id = f"draft_{self._draft_counter:04d}"
        self._drafts[draft_id] = {
            "thread_id": thread_id,
            "subject": subject,
            "body": body,
            "created_at": datetime.now(UTC).isoformat(),
        }
        return CreatedDraft(draft_id=draft_id, thread_id=thread_id)

    def all_drafts(self) -> dict[str, dict]:
        return dict(self._drafts)
