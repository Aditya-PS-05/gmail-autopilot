"""Priority ranking: VIPs, keywords, and LLM urgency drive the sort order
of action briefs in the run summary."""

from datetime import UTC, datetime

import pytest

from courier.api import run_autopilot
from courier.config import Config
from courier.models import Contact, EmailSummary, Mode, Priority, RelationshipSignal
from courier.priority import compute_priority


def test_compute_priority_vip_dominates():
    email = EmailSummary(
        id="e1",
        thread_id="t1",
        sender=Contact(email="alice@yc.com"),
        subject="hi",
        snippet="just checking in",
        received_at=datetime.now(UTC),
    )
    p = compute_priority(
        email,
        signal=None,
        memory=None,
        vip_emails={"alice@yc.com"},
        keywords=set(),
    )
    assert p.vip_match is True
    assert p.score == pytest.approx(1.0)


def test_compute_priority_keyword_in_subject():
    email = EmailSummary(
        id="e1",
        thread_id="t1",
        sender=Contact(email="recruiter@example.com"),
        subject="Offer letter — please review",
        snippet="see attached",
        received_at=datetime.now(UTC),
    )
    p = compute_priority(
        email,
        signal=None,
        memory=None,
        vip_emails=set(),
        keywords={"offer"},
    )
    assert p.keyword_match is True
    assert p.score == pytest.approx(0.6)


def test_compute_priority_combines_all_signals():
    email = EmailSummary(
        id="e1",
        thread_id="t1",
        sender=Contact(email="vip@example.com"),
        subject="urgent: please respond",
        snippet="action required",
        received_at=datetime.now(UTC),
    )
    sig = RelationshipSignal(
        email_id="e1", needs_reply=True, confidence=0.9, why_now="x", urgency=1.0
    )
    p = compute_priority(
        email,
        signal=sig,
        memory=None,
        vip_emails={"vip@example.com"},
        keywords={"urgent"},
    )
    # 1.0 (VIP) + 0.6 (keyword) + 0.0 (no memory) + 0.6 (urgency)
    assert p.score == pytest.approx(2.2)


def test_run_briefs_sorted_by_priority(tmp_db, mock_gmail, fake_llm, null_memory, monkeypatch):
    # Mark Jordan (Sequoia) as a VIP — should rank near the top regardless
    # of fetch order.
    monkeypatch.setenv("COURIER_VIPS", "jordan@sequoia.com")
    monkeypatch.setenv("COURIER_KEYWORDS", "")
    cfg = Config.from_env(mode=Mode.DRY_RUN, limit=10)

    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    assert run.action_briefs, "expected at least one brief"
    # Top brief should be the VIP
    assert run.action_briefs[0].contact.email == "jordan@sequoia.com"
    # Briefs should be in non-increasing priority order
    scores = [b.priority.score if b.priority else 0.0 for b in run.action_briefs]
    assert scores == sorted(scores, reverse=True)


def test_priority_attached_even_when_no_reply_needed(
    tmp_db, mock_gmail, fake_llm, null_memory
):
    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)
    # Newsletters / receipts get skipped_no_reply_needed but should still
    # have a priority score so they can be ranked in the summary.
    no_reply_briefs = [b for b in run.action_briefs if b.status == "skipped_no_reply_needed"]
    assert no_reply_briefs, "expected at least one no-reply brief in fixtures"
    for b in no_reply_briefs:
        assert isinstance(b.priority, Priority)


def test_memory_signal_flows_through_priority():
    """ContactMemory.relationship_strength feeds memory_signal directly."""
    email = EmailSummary(
        id="e1",
        thread_id="t1",
        sender=Contact(email="warm@example.com"),
        subject="catch up",
        snippet="hey",
        received_at=datetime.now(UTC),
    )
    from courier.models import ContactMemory

    mem = ContactMemory(contact_email="warm@example.com", relationship_strength=0.75)
    p = compute_priority(
        email,
        signal=None,
        memory=mem,
        vip_emails=set(),
        keywords=set(),
    )
    # 0.4 * 0.75 = 0.3
    assert p.memory_signal == 0.75
    assert p.score == pytest.approx(0.3)


def test_memory_signal_handles_none_strength():
    """ContactMemory exists but relationship_strength is None — should not crash."""
    email = EmailSummary(
        id="e1",
        thread_id="t1",
        sender=Contact(email="x@example.com"),
        subject="hi",
        snippet="",
        received_at=datetime.now(UTC),
    )
    from courier.models import ContactMemory

    mem = ContactMemory(contact_email="x@example.com", relationship_strength=None)
    p = compute_priority(
        email, signal=None, memory=mem, vip_emails=set(), keywords=set()
    )
    assert p.memory_signal == 0.0
    assert p.score == 0.0


def test_llm_urgency_flows_through_priority():
    """RelationshipSignal.urgency feeds llm_urgency directly."""
    email = EmailSummary(
        id="e1",
        thread_id="t1",
        sender=Contact(email="x@example.com"),
        subject="hi",
        snippet="",
        received_at=datetime.now(UTC),
    )
    sig = RelationshipSignal(
        email_id="e1", needs_reply=True, confidence=0.9, why_now="x", urgency=0.5
    )
    p = compute_priority(
        email, signal=sig, memory=None, vip_emails=set(), keywords=set()
    )
    # 0.6 * 0.5 = 0.3
    assert p.llm_urgency == 0.5
    assert p.score == pytest.approx(0.3)


def test_llm_urgency_defaults_to_zero_when_field_missing():
    """RelationshipSignal without explicit urgency defaults to 0 — backward
    compatible with real LLMs that don't return the field."""
    sig = RelationshipSignal(
        email_id="e1", needs_reply=True, confidence=0.9, why_now="x"
    )
    assert sig.urgency == 0.0


def test_e2e_memory_provider_lifts_known_contact(
    tmp_db, mock_gmail, fake_llm
):
    """Plug a memory provider that knows one sender; that sender's brief should
    get a higher priority than peers with no memory."""

    from courier.models import ContactMemory

    class StubMemory:
        def lookup(self, contact_email: str) -> ContactMemory | None:
            if contact_email == "alex@stripe.com":
                return ContactMemory(
                    contact_email=contact_email, relationship_strength=0.9
                )
            return None

    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(
        cfg, gmail=mock_gmail, llm=fake_llm, memory=StubMemory(), repo=tmp_db
    )
    alex_brief = next(
        (b for b in run.action_briefs if b.contact.email == "alex@stripe.com"), None
    )
    assert alex_brief is not None
    assert alex_brief.priority is not None
    assert alex_brief.priority.memory_signal == 0.9
    assert alex_brief.memory_used is True
