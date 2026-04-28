"""Priority scoring for inbox ranking.

Combines four signals into a single score so emails can be surfaced in the
order the user is most likely to care about:

    priority = 1.0 * vip_match
             + 0.6 * keyword_match
             + 0.4 * memory_signal
             + 0.6 * llm_urgency

Each signal is computed cheaply at brief-building time. Weights are static —
deterministic, debuggable, easy to override later via env vars if needed.
"""

from __future__ import annotations

from .models import ContactMemory, EmailSummary, Priority, RelationshipSignal

W_VIP = 1.0
W_KEYWORD = 0.6
W_MEMORY = 0.4
W_URGENCY = 0.6


def compute_priority(
    email: EmailSummary,
    *,
    signal: RelationshipSignal | None,
    memory: ContactMemory | None,
    vip_emails: set[str],
    keywords: set[str],
) -> Priority:
    sender = email.sender.email.lower()
    vip = sender in vip_emails

    haystack = f"{email.subject}\n{email.snippet}".lower()
    kw = bool(keywords) and any(k in haystack for k in keywords)

    mem = memory.relationship_strength if memory and memory.relationship_strength else 0.0
    urg = signal.urgency if signal else 0.0

    score = (
        W_VIP * float(vip)
        + W_KEYWORD * float(kw)
        + W_MEMORY * mem
        + W_URGENCY * urg
    )
    return Priority(
        score=score,
        vip_match=vip,
        keyword_match=kw,
        memory_signal=mem,
        llm_urgency=urg,
    )
