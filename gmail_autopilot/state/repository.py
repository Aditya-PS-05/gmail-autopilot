"""Thin SQLite wrapper. One connection per Repository instance.

All writes are autocommit so that workflow progress is durable even if the process
crashes mid-run. The idempotency table uses INSERT OR IGNORE so two racing writers
can never duplicate a key."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..models import AutoPilotRun, EmailActionBrief, StepResult

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


class Repository:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)  # autocommit
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ---- workflow runs ----

    def insert_run(self, run: AutoPilotRun, workflow_name: str) -> None:
        self._conn.execute(
            "INSERT INTO workflow_runs (id, workflow, mode, started_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (run.id, workflow_name, run.mode.value, run.started_at.isoformat(), run.status),
        )

    def finish_run(self, run: AutoPilotRun) -> None:
        self._conn.execute(
            "UPDATE workflow_runs "
            "SET finished_at=?, duration_ms=?, status=?, summary_json=? "
            "WHERE id=?",
            (
                (run.finished_at or datetime.now(UTC)).isoformat(),
                run.duration_ms,
                run.status,
                run.summary.model_dump_json() if run.summary else None,
                run.id,
            ),
        )

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, workflow, mode, started_at, status, duration_ms "
            "FROM workflow_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- email runs ----

    def insert_email_run(
        self,
        *,
        id: str,
        workflow_run_id: str,
        email_id: str,
        thread_id: str,
        contact_email: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO email_runs "
            "(id, workflow_run_id, email_id, thread_id, contact_email, status, started_at) "
            "VALUES (?, ?, ?, ?, ?, 'running', ?)",
            (
                id,
                workflow_run_id,
                email_id,
                thread_id,
                contact_email,
                datetime.now(UTC).isoformat(),
            ),
        )

    def finish_email_run(self, email_run_id: str, brief: EmailActionBrief) -> None:
        self._conn.execute(
            "UPDATE email_runs SET status=?, brief_json=?, error=?, finished_at=? WHERE id=?",
            (
                brief.status,
                brief.model_dump_json(),
                brief.error,
                datetime.now(UTC).isoformat(),
                email_run_id,
            ),
        )

    # ---- step results ----

    def insert_step(
        self,
        *,
        workflow_run_id: str,
        email_run_id: str | None,
        result: StepResult,
    ) -> None:
        self._conn.execute(
            "INSERT INTO step_results "
            "(workflow_run_id, email_run_id, step_name, status, started_at, "
            " duration_ms, input_hash, output_summary, error, retry_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                workflow_run_id,
                email_run_id,
                result.step_name,
                result.status.value,
                result.started_at.isoformat(),
                result.duration_ms,
                result.input_hash,
                result.output_summary,
                result.error,
                result.retry_count,
            ),
        )

    # ---- idempotency ----

    def drafted_thread_ids(self, workflow: str) -> set[str]:
        """Return all thread_ids that already have a draft for this workflow."""
        rows = self._conn.execute(
            "SELECT DISTINCT thread_id FROM idempotency_keys WHERE workflow=?",
            (workflow,),
        ).fetchall()
        return {row["thread_id"] for row in rows}

    def lookup_idempotency(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT draft_id FROM idempotency_keys WHERE key=?", (key,)
        ).fetchone()
        return row["draft_id"] if row else None

    def record_idempotency(
        self,
        *,
        key: str,
        workflow: str,
        thread_id: str,
        draft_id: str,
        workflow_run_id: str,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO idempotency_keys "
            "(key, workflow, thread_id, draft_id, workflow_run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key, workflow, thread_id, draft_id, workflow_run_id, datetime.now(UTC).isoformat()),
        )
