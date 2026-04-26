"""Bounded retry helper.

Only TransientError triggers a retry. Backoff is exponential with jitter, clamped.
This is deliberately small — there is no retry framework here, just one function."""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from typing import TypeVar

from ..errors import TransientError

R = TypeVar("R")
log = logging.getLogger(__name__)


def call_with_retry(
    fn: Callable[[], R],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.25,
    max_delay_s: float = 5.0,
) -> tuple[R, int]:
    """Run `fn`. On TransientError, sleep and retry. Returns (result, retry_count)
    so the engine can record retry stats on the step row.

    Set BRACE_RETRY_NO_SLEEP=1 in tests to skip the actual sleep."""
    no_sleep = os.environ.get("BRACE_RETRY_NO_SLEEP") == "1"
    attempt = 0
    while True:
        try:
            return fn(), attempt
        except TransientError as e:
            attempt += 1
            if attempt >= max_attempts:
                raise
            delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            delay = delay * (0.5 + random.random())
            log.warning(
                "transient error (attempt %d/%d): %s; sleeping %.2fs",
                attempt,
                max_attempts,
                e,
                delay,
            )
            if not no_sleep:
                time.sleep(delay)
