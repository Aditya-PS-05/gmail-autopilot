from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Mode(StrEnum):
    DRY_RUN = "dry-run"
    REAL = "real"


class Contact(BaseModel):
    name: str | None = None
    email: str


class EmailSummary(BaseModel):
    id: str
    thread_id: str
    sender: Contact
    subject: str
    snippet: str
    received_at: datetime


class Email(BaseModel):
    id: str
    thread_id: str
    sender: Contact
    recipients: list[Contact] = []
    subject: str
    body: str
    received_at: datetime


class Thread(BaseModel):
    id: str
    messages: list[Email]


class ContactMemory(BaseModel):
    """Optional contact context. Returned by a MemoryProvider (e.g. brace's contact graph).
    With NullMemoryProvider this is always None and the workflow runs as a generic responder."""

    contact_email: str
    last_interaction_at: datetime | None = None
    relationship_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    recent_signals: list[str] = []
    prior_thread_summary: str | None = None


class RelationshipSignal(BaseModel):
    email_id: str
    needs_reply: bool
    confidence: float = Field(ge=0.0, le=1.0)
    why_now: str
    urgency: float = Field(default=0.0, ge=0.0, le=1.0)


class Priority(BaseModel):
    """Composite priority score for an email. Higher score = surface first."""

    score: float
    vip_match: bool = False
    keyword_match: bool = False
    memory_signal: float = 0.0
    llm_urgency: float = 0.0


class DraftContent(BaseModel):
    thread_id: str
    subject: str
    body: str = Field(min_length=1, max_length=4000)


class CreatedDraft(BaseModel):
    draft_id: str
    thread_id: str
    was_idempotent_hit: bool = False


class StepStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    SKIPPED_DRY_RUN = "skipped_dry_run"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"


class StepResult(BaseModel):
    step_name: str
    status: StepStatus
    started_at: datetime
    duration_ms: int
    input_hash: str | None = None
    output_summary: str | None = None
    error: str | None = None
    retry_count: int = 0


BriefStatus = Literal[
    "replied_draft_created",
    "replied_dry_run",
    "skipped_no_reply_needed",
    "failed",
]


class EmailActionBrief(BaseModel):
    """The primary unit of output. One per email processed.
    Maps to a brace 'action brief' / Keep-Up entry."""

    email_id: str
    thread_id: str
    contact: Contact
    subject: str
    status: BriefStatus
    why_now: str | None = None
    signal_score: float | None = None
    suggested_message: DraftContent | None = None
    draft_id: str | None = None
    memory_used: bool = False
    priority: Priority | None = None
    error: str | None = None


class RunSummary(BaseModel):
    fetched: int
    already_drafted: int = 0
    needs_reply: int
    skipped_no_reply: int
    drafts_generated: int
    drafts_created: int
    failed: int


RunStatus = Literal["running", "completed", "completed_with_failures", "auth_failed"]


class AutoPilotRun(BaseModel):
    id: str
    mode: Mode
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    status: RunStatus = "running"
    action_briefs: list[EmailActionBrief] = []
    summary: RunSummary | None = None
