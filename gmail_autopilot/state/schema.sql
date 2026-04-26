CREATE TABLE IF NOT EXISTS workflow_runs (
    id              TEXT PRIMARY KEY,
    workflow        TEXT NOT NULL,
    mode            TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_ms     INTEGER,
    status          TEXT NOT NULL,
    summary_json    TEXT
);

CREATE TABLE IF NOT EXISTS email_runs (
    id              TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    email_id        TEXT NOT NULL,
    thread_id       TEXT NOT NULL,
    contact_email   TEXT NOT NULL,
    status          TEXT NOT NULL,
    brief_json      TEXT,
    error           TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_runs_workflow ON email_runs(workflow_run_id);

CREATE TABLE IF NOT EXISTS step_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    email_run_id    TEXT REFERENCES email_runs(id),
    step_name       TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    duration_ms     INTEGER,
    input_hash      TEXT,
    output_summary  TEXT,
    error           TEXT,
    retry_count     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_steps_workflow ON step_results(workflow_run_id);
CREATE INDEX IF NOT EXISTS idx_steps_email_run ON step_results(email_run_id);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key             TEXT PRIMARY KEY,
    workflow        TEXT NOT NULL,
    thread_id       TEXT NOT NULL,
    draft_id        TEXT NOT NULL,
    workflow_run_id TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
