from gmail_autopilot.api import run_autopilot
from gmail_autopilot.config import Config
from gmail_autopilot.models import Mode


def test_rerun_does_not_duplicate_drafts(tmp_db, mock_gmail, fake_llm, null_memory):
    """Two consecutive real-mode runs against the same inbox + deterministic LLM
    must NOT produce duplicate Gmail drafts. The second run's briefs reference
    the same draft IDs as the first run."""
    cfg = Config(mode=Mode.REAL, limit=10)

    run1 = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)
    drafts_after_run1 = dict(mock_gmail.all_drafts())
    assert run1.summary is not None and run1.summary.drafts_created > 0
    assert len(drafts_after_run1) == run1.summary.drafts_created

    run2 = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)
    drafts_after_run2 = mock_gmail.all_drafts()

    # No new drafts created in Gmail
    assert len(drafts_after_run2) == len(drafts_after_run1)

    # Briefs in run2 reference the original draft IDs
    ids_run1 = {b.draft_id for b in run1.action_briefs if b.draft_id}
    ids_run2 = {b.draft_id for b in run2.action_briefs if b.draft_id}
    assert ids_run1 == ids_run2
    assert len(ids_run1) > 0
