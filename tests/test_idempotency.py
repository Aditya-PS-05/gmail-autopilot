from gmail_autopilot.api import run_autopilot
from gmail_autopilot.config import Config
from gmail_autopilot.models import Mode


def test_rerun_does_not_duplicate_drafts(tmp_db, mock_gmail, fake_llm, null_memory):
    """Two consecutive real-mode runs against the same inbox must NOT produce
    duplicate Gmail drafts. On the second run, already-drafted threads are
    skipped entirely so no new drafts are created."""
    cfg = Config(mode=Mode.REAL, limit=10)

    run1 = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)
    drafts_after_run1 = dict(mock_gmail.all_drafts())
    assert run1.summary is not None and run1.summary.drafts_created > 0
    assert len(drafts_after_run1) == run1.summary.drafts_created

    run2 = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)
    drafts_after_run2 = mock_gmail.all_drafts()

    # No new drafts created in Gmail on the second run
    assert len(drafts_after_run2) == len(drafts_after_run1)

    # Second run skips all previously-drafted threads
    assert run2.summary is not None
    assert run2.summary.already_drafted == run1.summary.drafts_created
    assert run2.summary.drafts_created == 0
