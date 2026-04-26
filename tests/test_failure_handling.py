from gmail_autopilot.api import run_autopilot
from gmail_autopilot.config import Config
from gmail_autopilot.errors import PermanentError, TransientError, ValidationError
from gmail_autopilot.models import Mode


def test_one_email_fails_others_continue(tmp_db, mock_gmail, fake_llm, null_memory):
    """One Gmail PermanentError on read_thread should fail one email but NOT
    abort the run. Other emails should still produce drafts."""
    mock_gmail.fail_on_next_call("read_thread", PermanentError("simulated thread fetch failure"))

    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    assert run.summary is not None
    assert run.summary.failed == 1
    assert run.summary.drafts_generated >= 1
    assert run.status == "completed_with_failures"

    failed = [b for b in run.action_briefs if b.status == "failed"]
    assert len(failed) == 1
    assert "simulated thread fetch failure" in (failed[0].error or "")


def test_transient_error_is_retried(tmp_db, mock_gmail, fake_llm, null_memory):
    """A single TransientError on read_thread should be retried and succeed."""
    mock_gmail.fail_on_next_call("read_thread", TransientError("simulated timeout"))

    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    assert run.summary is not None
    assert run.summary.failed == 0
    assert run.status == "completed"


def test_malformed_llm_output_marks_email_failed(tmp_db, mock_gmail, fake_llm, null_memory):
    """ValidationError is a PermanentError subtype. A malformed-output failure
    on a single email's signal step should mark that email failed but allow
    the rest of the run to complete."""
    fake_llm.fail_on_next_call("RelationshipSignal", ValidationError("malformed JSON"))

    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    assert run.summary is not None
    failed = [b for b in run.action_briefs if b.status == "failed"]
    assert len(failed) == 1
    assert "malformed" in (failed[0].error or "").lower()
    # Run still produced drafts for the surviving emails
    assert run.summary.drafts_generated >= 1


def test_persisted_run_can_be_inspected(tmp_db, mock_gmail, fake_llm, null_memory):
    """After a run completes, the run row should be readable from SQLite."""
    cfg = Config(mode=Mode.DRY_RUN, limit=10)
    run = run_autopilot(cfg, gmail=mock_gmail, llm=fake_llm, memory=null_memory, repo=tmp_db)

    row = tmp_db.get_run(run.id)
    assert row is not None
    assert row["mode"] == "dry-run"
    assert row["status"] == "completed"
    assert row["duration_ms"] is not None
    assert row["summary_json"] is not None
