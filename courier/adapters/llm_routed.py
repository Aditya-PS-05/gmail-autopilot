"""Multi-provider LLM router.

Behavior on each `complete()` call:
  1. Pick the route for the given model_hint (e.g. "fast" / "smart" / "cheap").
  2. Try providers in order. Return the first success.
  3. On AuthError/PermanentError: fall through to the next provider.
  4. On TransientError: also fall through; only re-raise TransientError if
     ALL providers fail transiently. The engine's retry budget then kicks in.

This gives you per-task routing (different providers for fast vs smart),
provider-availability handling (skip any not configured), and failure
fallback (Claude down? GPT picks up) in one ~30-line class.

The default rankings are opinionated but every one is overrideable via env
vars — see `_build_auto_llm` in api.py.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from ..errors import AuthError, PermanentError, TransientError
from .llm_base import LLMClient

T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)


class RoutedLLM:
    """`routes` maps model_hint -> ordered [(provider_name, client), ...]."""

    def __init__(self, routes: dict[str, list[tuple[str, LLMClient]]]):
        if not routes or not any(routes.values()):
            raise ValueError("RoutedLLM requires at least one configured route")
        self._routes = routes
        self._default_hint = next(k for k, v in routes.items() if v)

    def complete(
        self,
        system: str,
        user: str,
        schema: type[T],
        model_hint: str = "fast",
    ) -> T:
        candidates = self._routes.get(model_hint) or self._routes[self._default_hint]
        transient_errors: list[Exception] = []
        last_perm: Exception | None = None
        for name, client in candidates:
            try:
                result = client.complete(system, user, schema, model_hint)
                log.info(
                    "llm_routed",
                    extra={"provider": name, "model_hint": model_hint},
                )
                return result
            except TransientError as e:
                log.warning("provider_transient_error provider=%s err=%s", name, e)
                transient_errors.append(e)
                continue
            except (AuthError, PermanentError) as e:
                log.warning("provider_permanent_error provider=%s err=%s", name, e)
                last_perm = e
                continue

        if transient_errors:
            raise TransientError(f"all routed providers failed transiently: {transient_errors}")
        if last_perm:
            raise last_perm
        raise PermanentError(f"no provider available for hint={model_hint}")
