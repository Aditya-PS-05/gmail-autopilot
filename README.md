# gmail-autopilot

A Gmail workflow runner that fetches recent emails, decides which deserve a reply, generates short draft replies, and creates Gmail drafts safely.

> **Hard rule:** this system never sends email. It creates drafts only, gated by `--mode`.

Built as a take-home assignment. Designed so the architecture and output fit naturally into a relationship-CRM "AutoPilot" model — multi-LLM-friendly, with a `MemoryProvider` extension point for contact context, and a structured `EmailActionBrief` output that drops into a Keep-Up / action-brief surface.

---

## Quickstart (no credentials needed)

This project uses [uv](https://docs.astral.sh/uv/) for environment and dependency management, and [ruff](https://docs.astral.sh/ruff/) for linting + formatting.

```bash
uv sync                                                    # creates .venv, installs deps + dev tools
uv run gmail-autopilot --mode dry-run --limit 6            # uses the entry point
# or:  uv run python -m gmail_autopilot --mode dry-run
```

Defaults use a mock Gmail client and a deterministic fake LLM, so the workflow runs end-to-end with zero credentials. You'll see a JSON `AutoPilotRun` on stdout and structured logs on stderr.

Run the test suite + lint:

```bash
uv run pytest tests/ -v
uv run ruff check .
uv run ruff format .
```

Inspect a previous run:

```bash
uv run gmail-autopilot --inspect run_abc123def012
# or open SQLite directly
sqlite3 runs.db "SELECT id, mode, status, duration_ms FROM workflow_runs ORDER BY started_at DESC LIMIT 5"
sqlite3 runs.db "SELECT step_name, status, retry_count, duration_ms FROM step_results WHERE workflow_run_id='run_...' ORDER BY id"
```

Run with real Anthropic + real Gmail:

```bash
uv sync --extra anthropic --extra google
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_CREDENTIALS_PATH=./credentials.json    # OAuth client_secrets.json from Google Cloud Console
uv run gmail-autopilot --gmail real --llm anthropic --mode dry-run
```

(First run opens a browser for OAuth; the resulting token is cached as `token.json`.)

---

## Architecture

Six layers, each replaceable. The boundary between layers is a `Protocol` or a typed Pydantic model — never a concrete class.

```
┌─────────────────────────────────────────────────┐
│ CLI (cli.py)  /  Library API (api.py)           │  two entrypoints, same engine
├─────────────────────────────────────────────────┤
│ Engine (engine/)                                │
│   - sequential pipeline with branching          │
│   - per-email isolation (one failure ≠ run abort) │
│   - dry-run gating on side-effect tools         │
├─────────────────────────────────────────────────┤
│ Tools (tools/)                                  │
│   list_recent_emails, read_thread,              │
│   score_relationship_signal, generate_draft,    │
│   create_draft  ← only side-effect tool         │
├─────────────────────────────────────────────────┤
│ Reliability (reliability/)                      │
│   typed errors, retry w/ jitter,                │
│   content-addressed idempotency,                │
│   structured JSON-line logger                   │
├─────────────────────────────────────────────────┤
│ State (state/)                                  │
│   SQLite: workflow_runs, email_runs,            │
│   step_results, idempotency_keys                │
├─────────────────────────────────────────────────┤
│ Adapters (adapters/)                            │
│   GmailClient: Mock | Real                      │
│   LLMClient:   Fake | Anthropic                 │
│                (Gemini/OpenAI extensible)       │
│   MemoryProvider: Null | (brace plug-in)        │
└─────────────────────────────────────────────────┘
```

### The five tools

| name | side-effect | what it does |
|---|---|---|
| `list_recent_emails` | no | seed step — fetch N most recent emails |
| `score_relationship_signal` | no | LLM step — `needs_reply` + `why_now` reasoning |
| `read_thread` | no | branch — only runs when `needs_reply == true` |
| `generate_draft` | no | LLM step — produces a validated `DraftContent` |
| `create_draft` | **yes** | the only write — gated by mode, idempotency-checked |

### Dry-run vs real mode

The engine refuses to execute any tool with `is_side_effect=True` while `mode=="dry-run"`. The step is recorded as `skipped_dry_run` with a "would have created draft" note. The action brief still carries the proposed `suggested_message` so a reviewer sees exactly what *would* have been written.

### Idempotency

Before `create_draft` calls Gmail, it computes:

```
key = sha256(workflow_name | thread_id | normalized(body))
```

If the key exists in the `idempotency_keys` table, the existing draft id is reused and the step records `was_idempotent_hit=true`. Otherwise we create the draft and persist the key. **Reruns produce zero duplicate drafts** as long as the LLM produces the same body for the same input (deterministic in tests; near-deterministic with a low-temperature production LLM).

Why content-addressed instead of just `(thread_id)`? If a later run produces a *meaningfully different* draft for the same thread, that's a legitimately new artifact — we should not suppress it. We only suppress byte-identical draft content.

There is a small known window: if Gmail succeeds but the local DB write that follows it fails, a rerun may create a duplicate. That's acknowledged in `tools/create_draft.py`. A two-phase commit (record-pending → commit) would close the gap; not implemented here as the assignment specifies "basic idempotency".

### Error model

Three error types, normalized at every adapter boundary:

| error | behavior |
|---|---|
| `TransientError` | retried with exponential backoff + jitter, max 3 attempts |
| `PermanentError` | recorded on the email's brief; run continues to the next email |
| `AuthError` | fatal — aborts the entire run |

`ValidationError` is a subtype of `PermanentError` for typed/schema failures.

### Per-email isolation

Each email runs in its own try/except inside the fan-out. A failure on one email never poisons the rest of the run. The `RunSummary` reports `failed` count alongside `drafts_created` so the operator sees both successes and failures in one place.

### Observability

Every step writes a row to `step_results` with input hash, duration, retry count, status, and a redacted output summary. Stderr emits structured JSON lines tagged with `workflow_run_id`, `step_name`, `tool_name`, `mode`, `duration_ms`, `retry_count`. **Email bodies are never logged** — only ids, subjects, and aggregate counts.

### Brace fit

The codebase is deliberately shaped for a relationship-CRM ("AutoPilot") backend:

- The output is a stream of `EmailActionBrief` objects with a `why_now` reasoning string — the same shape as a Keep-Up entry / action brief.
- The `LLMClient` interface accepts `model_hint` of `"fast"` / `"smart"` / `"cheap"`, so callers can route across providers (Gemini / Claude / GPT).
- `MemoryProvider` is an injectable extension point. With `NullMemoryProvider`, the workflow runs as a generic responder. Plug in a contact-graph provider and the same workflow becomes network-aware: signal scoring and draft generation receive richer context (last interaction, recent signals, prior thread summary).
- Library-first packaging: `run_autopilot(config) -> AutoPilotRun` is what a backend service would import directly. The CLI is a thin wrapper.

This codebase makes no claim of integrating with brace.so directly — there is no public brace API. It is shaped to be folded into one.

---

## Test coverage

`pytest tests/` — 8 tests, all green (~1s). Every failure mode runs against the mocks; no network or credentials.

| test | what it proves |
|---|---|
| `test_dry_run_does_not_create_drafts` | dry-run respects the side-effect gate |
| `test_real_mode_creates_drafts` | real-mode actually writes to (mock) Gmail |
| `test_rerun_does_not_duplicate_drafts` | idempotency works across runs |
| `test_one_email_fails_others_continue` | per-email isolation under permanent errors |
| `test_transient_error_is_retried` | timeouts retry transparently |
| `test_malformed_llm_output_marks_email_failed` | LLM `ValidationError` is recorded, not crashed |
| `test_persisted_run_can_be_inspected` | run state is durable in SQLite |
| `test_emails_without_reply_skip_thread_and_draft` | branching cuts work |

`MockGmailClient.fail_on_next_call(operation, error)` and `FakeLLMClient.fail_on_next_call(schema_name, error)` make failure simulation a one-liner.

---

## Project layout

```
gmail_autopilot/
├── api.py                         # public entrypoint: run_autopilot(...)
├── cli.py                         # argparse wrapper
├── __main__.py                    # `python -m gmail_autopilot`
├── config.py                      # env + override config
├── errors.py                      # 4 typed errors
├── models.py                      # all Pydantic schemas
├── adapters/
│   ├── gmail_base.py              # GmailClient Protocol
│   ├── gmail_mock.py              # in-memory; supports fail_on_next_call
│   ├── gmail_real.py              # google-api-python-client; OAuth
│   ├── llm_base.py                # LLMClient Protocol
│   ├── llm_anthropic.py           # Claude client; JSON output
│   ├── llm_fake.py                # deterministic; supports fail_on_next_call
│   ├── memory_base.py             # MemoryProvider Protocol
│   └── memory_null.py             # default (returns None)
├── reliability/
│   ├── retry.py                   # call_with_retry, jitter, BRACE_RETRY_NO_SLEEP
│   ├── idempotency.py             # draft_idempotency_key
│   └── logger.py                  # JsonLineFormatter, configure_logging
├── state/
│   ├── schema.sql                 # 4 tables
│   └── repository.py              # SQLite wrapper
├── tools/
│   ├── base.py                    # Tool ABC + ToolContext
│   ├── list_recent_emails.py
│   ├── read_thread.py
│   ├── score_relationship_signal.py
│   ├── generate_draft.py
│   └── create_draft.py            # the only is_side_effect=True tool
├── engine/
│   ├── step.py                    # Step dataclass
│   └── runner.py                  # WorkflowRunner
├── workflows/
│   └── autopilot_inbox.py         # canonical workflow definition
└── fixtures/
    └── mock_inbox.json            # 6 emails: 3 need reply, 3 don't
```

---

## How I used AI coding tools

**What I designed myself**
- The layer split (adapters / tools / engine / state / reliability) and the rule that nothing crosses a layer except via a `Protocol` or a Pydantic model.
- The `is_side_effect` flag on `Tool`, which collapses dry-run mode to a one-line gate in the engine instead of a fork in every tool.
- The content-addressed idempotency key keyed on `(workflow, thread_id, normalized_body)`, including the deliberate choice to *not* key on `thread_id` alone.
- The three-error taxonomy (`TransientError` / `PermanentError` / `AuthError`) and the rule that adapters normalize every external exception into one of these.
- The `MemoryProvider` extension point — the brace-shaped hook that lets contact context flow into both the classifier and the draft generator without changing the workflow.
- The `EmailActionBrief` output shape with `why_now` and `signal_score`, designed to drop into an action-brief / Keep-Up surface.
- The decision to make the engine ~250 lines and *not* build Temporal/Airflow.

**What I asked AI to generate**
- Boilerplate Pydantic field declarations.
- The OAuth bootstrapping and MIME-tree walking in `gmail_real.py`.
- The SQL schema string.
- The fixture inbox JSON (6 emails, mix of needs-reply / no-reply).
- The structured-log formatter skeleton.

**What I modified or rejected**
- AI's first cut at the runner used a generic try/except that also swallowed `AuthError`. I rewrote the auth path so an auth failure aborts the entire run instead of being recorded on a single email.
- AI proposed wrapping every tool call in a generic retry. I narrowed retries to `TransientError` only (so malformed JSON from the LLM does not silently retry forever) and made `max_attempts` a per-step setting.
- AI's idempotency suggestion was keyed on `(thread_id)` only. Rejected because legitimately different LLM drafts on a later run would be suppressed; switched to content-addressed.
- AI wanted to log full email bodies for "easier debugging." Rejected — bodies never enter logs; only ids, subjects, and counts.

**How I tested generated code**
- A hand-written end-to-end smoke test (`python -m gmail_autopilot --mode dry-run`) exercises the full pipeline.
- 8 pytest tests cover every failure mode using `MockGmailClient.fail_on_next_call(...)` and `FakeLLMClient.fail_on_next_call(...)`. No network or credentials.

**What I avoided delegating**
- The trust boundary. Deciding which step is a "side effect", what gets logged, what counts as transient vs permanent — those decisions live in my head, not in a prompt.
- The output shape. The brace vocabulary alignment (`AutoPilotRun`, `EmailActionBrief`, `why_now`, `MemoryProvider`) was a deliberate architectural choice, not a generated artifact.
- The known-limitation note in `tools/create_draft.py` about the create-then-record window. AI would have written confident "this is fully atomic" claims; I explicitly documented the gap.
