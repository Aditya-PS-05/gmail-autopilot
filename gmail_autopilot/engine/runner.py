"""Workflow runner.

Responsibilities:
  - run the seed step once (e.g. list_recent_emails)
  - fan out: run the per-email pipeline for each email, isolated by try/except
  - branch: skip a step when its condition closure returns False
  - dry-run gate: refuse side-effect tools when mode == "dry-run"
  - persist a row for every step into the repository
  - return a fully-built AutoPilotRun with action briefs and a summary
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..adapters.gmail_base import GmailClient
from ..adapters.llm_base import LLMClient
from ..adapters.memory_base import MemoryProvider
from ..errors import AuthError, WorkflowError
from ..models import (
    AutoPilotRun,
    EmailActionBrief,
    EmailSummary,
    Mode,
    RunSummary,
    StepResult,
    StepStatus,
)
from ..reliability.retry import call_with_retry
from ..state.repository import Repository
from ..tools.base import ToolContext
from .events import EmailCompleted, EmailsFetched, ProgressEvent, RunFinished, RunStarted
from .step import Step

log = logging.getLogger(__name__)


class WorkflowRunner:
    def __init__(
        self,
        *,
        workflow_name: str,
        seed_step: Step,
        per_email_steps: list[Step],
        gmail: GmailClient,
        llm: LLMClient,
        memory: MemoryProvider,
        repo: Repository,
        mode: Mode,
    ):
        self.workflow_name = workflow_name
        self.seed_step = seed_step
        self.per_email_steps = per_email_steps
        self.gmail = gmail
        self.llm = llm
        self.memory = memory
        self.repo = repo
        self.mode = mode

    # ---- public ----

    def run(
        self,
        *,
        limit: int,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> AutoPilotRun:
        notify = on_progress or (lambda _e: None)
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = AutoPilotRun(
            id=run_id,
            mode=self.mode,
            started_at=datetime.now(UTC),
            status="running",
        )
        self.repo.insert_run(run, self.workflow_name)
        log.info(
            "workflow_started",
            extra={"workflow_run_id": run_id, "mode": self.mode.value},
        )
        notify(RunStarted(run_id=run_id, mode=self.mode.value, workflow=self.workflow_name))
        ctx = ToolContext(
            workflow_name=self.workflow_name,
            workflow_run_id=run_id,
            mode=self.mode.value,
            gmail=self.gmail,
            llm=self.llm,
            memory=self.memory,
            repo=self.repo,
        )
        t_start = time.monotonic()

        # 1. Seed
        try:
            seed_inp = self.seed_step.input_builder({"limit": limit})
            seed_out = self._run_tool(self.seed_step, seed_inp, ctx, email_run_id=None)
            # Deduplicate by thread_id — Gmail returns individual messages so the
            # same thread can appear multiple times. Keep the first (most recent).
            seen: set[str] = set()
            emails: list[EmailSummary] = []
            for _e in seed_out.emails:
                if _e.thread_id not in seen:
                    seen.add(_e.thread_id)
                    emails.append(_e)

            # Skip threads that already have a draft from a previous run so
            # reruns only process genuinely new threads.
            drafted = self.repo.drafted_thread_ids(self.workflow_name)
            already_drafted_count = sum(1 for e in emails if e.thread_id in drafted)
            emails = [e for e in emails if e.thread_id not in drafted]
            if already_drafted_count:
                log.info(
                    "skipping_already_drafted",
                    extra={
                        "count": already_drafted_count,
                        "workflow_run_id": run_id,
                    },
                )
        except AuthError:
            run.status = "auth_failed"
            run.finished_at = datetime.now(UTC)
            run.duration_ms = int((time.monotonic() - t_start) * 1000)
            self.repo.finish_run(run)
            log.error("auth_failed_aborting", extra={"workflow_run_id": run_id})
            raise
        except WorkflowError as e:
            run.status = "completed_with_failures"
            run.finished_at = datetime.now(UTC)
            run.duration_ms = int((time.monotonic() - t_start) * 1000)
            run.summary = RunSummary(
                fetched=0,
                needs_reply=0,
                skipped_no_reply=0,
                drafts_generated=0,
                drafts_created=0,
                failed=0,
            )
            self.repo.finish_run(run)
            log.error("seed_failed: %s", e, extra={"workflow_run_id": run_id})
            notify(RunFinished(run=run))
            return run

        notify(EmailsFetched(emails=emails))

        # 2. Fan out (per-email isolation)
        any_failed = False
        total = len(emails)
        for i, email in enumerate(emails, start=1):
            brief = self._process_email(email, ctx)
            run.action_briefs.append(brief)
            if brief.status == "failed":
                any_failed = True
            notify(EmailCompleted(brief=brief, index=i, total=total))

        # 3. Summarize
        run.finished_at = datetime.now(UTC)
        run.duration_ms = int((time.monotonic() - t_start) * 1000)
        run.status = "completed_with_failures" if any_failed else "completed"
        run.summary = self._build_summary(emails, run.action_briefs, already_drafted_count)
        self.repo.finish_run(run)
        log.info(
            "workflow_finished",
            extra={
                "workflow_run_id": run_id,
                "mode": self.mode.value,
                "duration_ms": run.duration_ms,
            },
        )
        notify(RunFinished(run=run))
        return run

    # ---- internals ----

    def _process_email(self, email: EmailSummary, ctx: ToolContext) -> EmailActionBrief:
        email_run_id = f"er_{uuid.uuid4().hex[:10]}"
        ctx.email_run_id = email_run_id
        self.repo.insert_email_run(
            id=email_run_id,
            workflow_run_id=ctx.workflow_run_id,
            email_id=email.id,
            thread_id=email.thread_id,
            contact_email=email.sender.email,
        )
        brief = EmailActionBrief(
            email_id=email.id,
            thread_id=email.thread_id,
            contact=email.sender,
            subject=email.subject,
            status="failed",  # default until success/skip path proves otherwise
        )
        state: dict[str, Any] = {"email": email}

        # Inject contact memory once for the whole pipeline
        try:
            mem = self.memory.lookup(email.sender.email)
            if mem:
                state["memory"] = mem
                brief.memory_used = True
        except Exception as e:
            log.warning(
                "memory_lookup_failed: %s",
                e,
                extra={"email_id": email.id, "workflow_run_id": ctx.workflow_run_id},
            )

        try:
            for step in self.per_email_steps:
                # Branch: skip when condition is False
                if step.condition is not None and not step.condition(state):
                    self.repo.insert_step(
                        workflow_run_id=ctx.workflow_run_id,
                        email_run_id=email_run_id,
                        result=StepResult(
                            step_name=step.name,
                            status=StepStatus.SKIPPED,
                            started_at=datetime.now(UTC),
                            duration_ms=0,
                        ),
                    )
                    continue

                # Dry-run gate: never execute side-effect tools in dry-run
                if step.tool.is_side_effect and self.mode == Mode.DRY_RUN:
                    self.repo.insert_step(
                        workflow_run_id=ctx.workflow_run_id,
                        email_run_id=email_run_id,
                        result=StepResult(
                            step_name=step.name,
                            status=StepStatus.SKIPPED_DRY_RUN,
                            started_at=datetime.now(UTC),
                            duration_ms=0,
                            output_summary="would have created draft",
                        ),
                    )
                    log.info(
                        "dry_run_skip_side_effect",
                        extra={
                            "step_name": step.name,
                            "tool_name": step.tool.name,
                            "email_id": email.id,
                            "mode": self.mode.value,
                            "workflow_run_id": ctx.workflow_run_id,
                        },
                    )
                    continue

                inp = step.input_builder(state)
                out = self._run_tool(
                    step,
                    inp,
                    ctx,
                    email_run_id=email_run_id,
                    max_attempts=step.max_attempts,
                )
                state[step.output_key] = out

            brief = self._build_brief(brief, state)
            self.repo.finish_email_run(email_run_id, brief)
            return brief

        except WorkflowError as e:
            brief.status = "failed"
            brief.error = f"{type(e).__name__}: {str(e)[:200]}"
            self.repo.finish_email_run(email_run_id, brief)
            log.error(
                "email_failed: %s",
                e,
                extra={"email_id": email.id, "workflow_run_id": ctx.workflow_run_id},
            )
            return brief

    def _run_tool(
        self,
        step: Step,
        inp: Any,
        ctx: ToolContext,
        *,
        email_run_id: str | None,
        max_attempts: int = 3,
    ) -> Any:
        started_at = datetime.now(UTC)
        t0 = time.monotonic()
        input_hash = step.tool.hash_input(inp) if hasattr(inp, "model_dump") else None
        try:
            output, retry_count = call_with_retry(
                lambda: step.tool.execute(inp, ctx),
                max_attempts=max_attempts,
            )
        except WorkflowError as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            self.repo.insert_step(
                workflow_run_id=ctx.workflow_run_id,
                email_run_id=email_run_id,
                result=StepResult(
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    input_hash=input_hash,
                    error=f"{type(e).__name__}: {e}",
                ),
            )
            log.error(
                "step_failed",
                extra={
                    "step_name": step.name,
                    "tool_name": step.tool.name,
                    "email_id": email_run_id or "",
                    "workflow_run_id": ctx.workflow_run_id,
                    "duration_ms": duration_ms,
                },
            )
            raise

        duration_ms = int((time.monotonic() - t0) * 1000)
        summary = type(output).__name__
        # Custom one-line summaries for the high-signal outputs (no PII)
        if hasattr(output, "created") and hasattr(output.created, "draft_id"):
            summary = (
                f"created draft={output.created.draft_id} "
                f"idempotent={output.created.was_idempotent_hit}"
            )
        elif hasattr(output, "signal"):
            summary = (
                f"needs_reply={output.signal.needs_reply} confidence={output.signal.confidence:.2f}"
            )

        self.repo.insert_step(
            workflow_run_id=ctx.workflow_run_id,
            email_run_id=email_run_id,
            result=StepResult(
                step_name=step.name,
                status=StepStatus.SUCCEEDED,
                started_at=started_at,
                duration_ms=duration_ms,
                input_hash=input_hash,
                output_summary=summary,
                retry_count=retry_count,
            ),
        )
        log.info(
            "step_succeeded",
            extra={
                "step_name": step.name,
                "tool_name": step.tool.name,
                "duration_ms": duration_ms,
                "retry_count": retry_count,
                "workflow_run_id": ctx.workflow_run_id,
            },
        )
        return output

    @staticmethod
    def _build_brief(brief: EmailActionBrief, state: dict[str, Any]) -> EmailActionBrief:
        signal_out = state.get("signal_out")
        if signal_out is not None:
            brief.signal_score = signal_out.signal.confidence
            brief.why_now = signal_out.signal.why_now
            if not signal_out.signal.needs_reply:
                brief.status = "skipped_no_reply_needed"
                return brief

        draft_out = state.get("draft_out")
        if draft_out is not None:
            brief.suggested_message = draft_out.draft

        created_out = state.get("created_out")
        if created_out is not None:
            brief.draft_id = created_out.created.draft_id
            brief.status = "replied_draft_created"
        elif draft_out is not None:
            brief.status = "replied_dry_run"
        # else: brief.status stays "failed" (no signal => something broke earlier)
        return brief

    @staticmethod
    def _build_summary(
        emails: list[EmailSummary],
        briefs: list[EmailActionBrief],
        already_drafted: int = 0,
    ) -> RunSummary:
        return RunSummary(
            fetched=len(emails),
            already_drafted=already_drafted,
            needs_reply=sum(
                1 for b in briefs if b.status in ("replied_draft_created", "replied_dry_run")
            ),
            skipped_no_reply=sum(1 for b in briefs if b.status == "skipped_no_reply_needed"),
            drafts_generated=sum(1 for b in briefs if b.suggested_message is not None),
            drafts_created=sum(1 for b in briefs if b.draft_id is not None),
            failed=sum(1 for b in briefs if b.status == "failed"),
        )
