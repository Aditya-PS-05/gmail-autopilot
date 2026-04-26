"""Structured JSON-line logging.

Every log carries the workflow_run_id when available, plus step_name, tool_name,
mode, duration_ms, retry_count when set on the LogRecord via `extra=`. Email
bodies are never logged."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_TRACKED_EXTRAS = (
    "workflow_run_id",
    "email_id",
    "step_name",
    "tool_name",
    "mode",
    "duration_ms",
    "retry_count",
)


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _TRACKED_EXTRAS:
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonLineFormatter) for h in root.handlers):
        return
    root.setLevel(level)
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(JsonLineFormatter())
    root.addHandler(h)
