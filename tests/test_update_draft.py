"""Tests for the update_draft Gmail operation (used by the post-run review TUI)."""

import pytest

from courier.adapters.gmail_mock import MockGmailClient
from courier.errors import PermanentError


def test_update_draft_replaces_body_in_place():
    gmail = MockGmailClient()
    created = gmail.create_draft("thread_001", "Re: hi", "original body")
    assert gmail.all_drafts()[created.draft_id]["body"] == "original body"

    updated = gmail.update_draft(created.draft_id, "Re: hi", "edited body")

    assert updated.draft_id == created.draft_id
    assert updated.thread_id == "thread_001"
    assert gmail.all_drafts()[created.draft_id]["body"] == "edited body"


def test_update_draft_can_change_subject_too():
    gmail = MockGmailClient()
    created = gmail.create_draft("thread_001", "Re: hi", "body")

    gmail.update_draft(created.draft_id, "Re: better subject", "body")

    assert gmail.all_drafts()[created.draft_id]["subject"] == "Re: better subject"


def test_update_draft_records_updated_at():
    gmail = MockGmailClient()
    created = gmail.create_draft("thread_001", "Re: hi", "body")

    gmail.update_draft(created.draft_id, "Re: hi", "edited")

    assert "updated_at" in gmail.all_drafts()[created.draft_id]


def test_update_draft_unknown_id_raises_permanent():
    gmail = MockGmailClient()

    with pytest.raises(PermanentError):
        gmail.update_draft("nonexistent_id", "Re: hi", "body")
