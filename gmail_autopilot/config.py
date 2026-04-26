from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .models import Mode


@dataclass(frozen=True)
class Config:
    mode: Mode = Mode.DRY_RUN
    limit: int = 10
    workflow: str = "autopilot_inbox"
    db_path: Path = field(default_factory=lambda: Path("runs.db"))
    gmail_backend: str = "mock"  # "mock" | "real"
    llm_backend: str = "fake"  # "fake" | "anthropic" | "openai" | "grok" | "auto"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    xai_api_key: str | None = None
    google_credentials_path: Path | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, **overrides) -> Config:
        # Auto-load .env from cwd (or any parent dir) before reading os.environ.
        # `override=False` means real shell exports take precedence over .env.
        load_dotenv(override=False)
        gp = os.environ.get("GOOGLE_CREDENTIALS_PATH")
        defaults = dict(
            mode=Mode(os.environ.get("BRACE_MODE", "dry-run")),
            limit=int(os.environ.get("BRACE_LIMIT", "10")),
            workflow=os.environ.get("BRACE_WORKFLOW", "autopilot_inbox"),
            db_path=Path(os.environ.get("BRACE_DB_PATH", "runs.db")),
            gmail_backend=os.environ.get("BRACE_GMAIL_BACKEND", "mock"),
            llm_backend=os.environ.get("BRACE_LLM_BACKEND", "fake"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            xai_api_key=os.environ.get("XAI_API_KEY") or None,
            google_credentials_path=Path(gp) if gp else None,
            log_level=os.environ.get("BRACE_LOG_LEVEL", "INFO"),
        )
        defaults.update(overrides)
        return cls(**defaults)
