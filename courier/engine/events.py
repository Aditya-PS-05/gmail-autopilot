"""Progress events emitted by WorkflowRunner.

An external observer (CLI UI, log shipper, future web dashboard) can subscribe
to these without polling the SQLite store or parsing log lines."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import AutoPilotRun, EmailActionBrief, EmailSummary


@dataclass
class RunStarted:
    run_id: str
    mode: str
    workflow: str


@dataclass
class EmailsFetched:
    emails: list[EmailSummary]


@dataclass
class EmailCompleted:
    brief: EmailActionBrief
    index: int  # 1-based
    total: int


@dataclass
class RunFinished:
    run: AutoPilotRun


ProgressEvent = RunStarted | EmailsFetched | EmailCompleted | RunFinished
