"""Deterministic LLM stub. Picks a canned response by inspecting the prompt.

Used for tests and credential-free demos. Supports failure injection so we can
test retry / malformed-output / permanent-error paths without a real model."""

from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from ..errors import ValidationError

T = TypeVar("T", bound=BaseModel)


_NEEDS_REPLY_KEYWORDS = (
    "?",
    "question",
    "asap",
    "please",
    "let me know",
    "available",
    "could you",
    "follow up",
    "follow-up",
    "send when",
    "what's",
    "whats",
    "how do",
)

_HIGH_URGENCY_KEYWORDS = (
    "asap",
    "urgent",
    "offer",
    "interview",
    "deadline",
    "today",
    "tomorrow",
    "action required",
    "blocked",
)


class FakeLLMClient:
    def __init__(self) -> None:
        self._failures: list[dict] = []

    def fail_on_next_call(self, kind: str, error: Exception) -> None:
        """`kind` is the schema class name (e.g. 'RelationshipSignal') or '*' for any."""
        self._failures.append({"kind": kind, "error": error})

    def _maybe_fail(self, schema: type) -> None:
        for i, f in enumerate(self._failures):
            if f["kind"] in (schema.__name__, "*"):
                err = f["error"]
                self._failures.pop(i)
                raise err

    def complete(
        self,
        system: str,
        user: str,
        schema: type[T],
        model_hint: str = "fast",
    ) -> T:
        self._maybe_fail(schema)
        name = schema.__name__
        if name == "RelationshipSignal":
            return self._fake_signal(user, schema)
        if name == "DraftContent":
            return self._fake_draft(user, schema)
        raise ValidationError(f"FakeLLMClient has no canned response for {name}")

    def _fake_signal(self, user: str, schema: type[T]) -> T:
        text = user.lower()
        m_id = re.search(r"email_id:\s*([\w-]+)", user)
        email_id = m_id.group(1) if m_id else "unknown"
        needs_reply = any(kw in text for kw in _NEEDS_REPLY_KEYWORDS)
        # newsletter / receipts / no-reply senders never need a reply
        if any(s in text for s in ("no-reply", "noreply", "newsletter", "receipt", "marketing")):
            needs_reply = False
        why = (
            "Sender asked a direct question or used follow-up language."
            if needs_reply
            else "No question detected; appears informational or transactional."
        )
        urgency = 0.85 if any(kw in text for kw in _HIGH_URGENCY_KEYWORDS) else 0.3
        return schema.model_validate(
            {
                "email_id": email_id,
                "needs_reply": needs_reply,
                "confidence": 0.78 if needs_reply else 0.62,
                "why_now": why,
                "urgency": urgency,
            }
        )

    def _fake_draft(self, user: str, schema: type[T]) -> T:
        m_thread = re.search(r"thread_id:\s*([\w-]+)", user)
        m_subject = re.search(r"subject:\s*([^\n]+)", user)
        thread_id = m_thread.group(1) if m_thread else "thread_unknown"
        subj = m_subject.group(1).strip() if m_subject else "Quick reply"
        if not subj.lower().startswith("re:"):
            subj = f"Re: {subj}"
        body = (
            "Hi,\n\nThanks for reaching out. I'll take a look and get back to you shortly.\n\nBest,"
        )
        return schema.model_validate(
            {
                "thread_id": thread_id,
                "subject": subj,
                "body": body,
            }
        )
