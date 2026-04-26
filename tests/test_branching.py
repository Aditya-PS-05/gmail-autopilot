from courier.api import run_autopilot
from courier.config import Config
from courier.models import Mode


def test_emails_without_reply_skip_thread_and_draft(tmp_db, mock_gmail, fake_llm, null_memory):
    """Emails the classifier marks needs_reply=False must NOT have read_thread,
    generate_draft, or create_draft executed against them."""
    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    skipped = [b for b in run.action_briefs if b.status == "skipped_no_reply_needed"]
    assert len(skipped) > 0
    for brief in skipped:
        assert brief.suggested_message is None
        assert brief.draft_id is None

    # The newsletter, the marketing email, and the receipt should all skip
    skipped_emails = {b.email_id for b in skipped}
    assert "msg_002" in skipped_emails  # newsletter
    assert "msg_004" in skipped_emails  # marketing
    assert "msg_006" in skipped_emails  # receipt
