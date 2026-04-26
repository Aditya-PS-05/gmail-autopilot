"""Content-addressed idempotency keys for draft creation.

Keying on (workflow, thread_id, normalized_body) means:
- Re-running the same workflow on the same thread with the same draft body
  reuses the existing draft, never creates a duplicate.
- If the LLM proposes a meaningfully different draft on a later run, the body
  hash differs and the new draft IS created — that's intentional, not a bug.
- Whitespace differences alone do not create new drafts."""

from __future__ import annotations

import hashlib


def draft_idempotency_key(workflow_name: str, thread_id: str, body: str) -> str:
    norm_body = " ".join(body.split())
    payload = f"{workflow_name}|{thread_id}|{norm_body}".encode()
    return hashlib.sha256(payload).hexdigest()[:32]
