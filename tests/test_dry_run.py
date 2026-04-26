from gmail_autopilot.api import run_autopilot
from gmail_autopilot.config import Config
from gmail_autopilot.models import Mode


def test_dry_run_does_not_create_drafts(tmp_db, mock_gmail, fake_llm, null_memory):
    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    assert run.mode == Mode.DRY_RUN
    assert run.summary is not None
    assert run.summary.fetched == 6
    assert run.summary.drafts_generated > 0
    assert run.summary.drafts_created == 0
    assert mock_gmail.all_drafts() == {}

    for brief in run.action_briefs:
        if brief.suggested_message is not None:
            assert brief.status == "replied_dry_run"
            assert brief.draft_id is None


def test_real_mode_creates_drafts(tmp_db, mock_gmail, fake_llm, null_memory):
    cfg = Config(mode=Mode.REAL, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    assert run.summary is not None
    assert run.summary.drafts_created > 0
    assert len(mock_gmail.all_drafts()) == run.summary.drafts_created

    for brief in run.action_briefs:
        if brief.status == "replied_draft_created":
            assert brief.draft_id is not None
            assert brief.draft_id in mock_gmail.all_drafts()
