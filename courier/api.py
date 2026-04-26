"""Public library entrypoint. The CLI is a thin wrapper around `run_autopilot`.

Every dependency is injectable so callers (tests, brace's backend) can plug in
their own gmail / llm / memory provider without changing the engine."""

from __future__ import annotations

import os
from collections.abc import Callable

from .adapters.gmail_base import GmailClient
from .adapters.gmail_mock import MockGmailClient
from .adapters.llm_base import LLMClient
from .adapters.llm_fake import FakeLLMClient
from .adapters.memory_base import MemoryProvider
from .adapters.memory_null import NullMemoryProvider
from .config import Config
from .engine.events import ProgressEvent
from .engine.runner import WorkflowRunner
from .models import AutoPilotRun
from .reliability.logger import configure_logging
from .state.repository import Repository
from .workflows.autopilot_inbox import WORKFLOW_NAME, per_email_steps, seed_step

# Default per-hint provider rankings used by the `auto` backend. Justified in
# the README. Override per hint via BRACE_LLM_PREFERENCE_FAST / _SMART / _CHEAP
# (comma-separated provider names: anthropic, openai, grok).
_AUTO_DEFAULTS: dict[str, list[str]] = {
    "fast": ["openai", "grok", "anthropic"],
    "smart": ["anthropic", "openai", "grok"],
    "cheap": ["grok", "openai", "anthropic"],
}


def _build_gmail(config: Config) -> GmailClient:
    if config.gmail_backend == "mock":
        return MockGmailClient()
    if config.gmail_backend == "real":
        from .adapters.gmail_real import RealGmailClient

        if not config.google_credentials_path:
            raise RuntimeError("GOOGLE_CREDENTIALS_PATH required for real Gmail backend")
        return RealGmailClient(config.google_credentials_path)
    raise ValueError(f"unknown gmail backend: {config.gmail_backend}")


def _build_llm(config: Config) -> LLMClient:
    if config.llm_backend == "fake":
        return FakeLLMClient()
    if config.llm_backend == "anthropic":
        from .adapters.llm_anthropic import AnthropicLLM

        if not config.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY required for anthropic backend")
        return AnthropicLLM(config.anthropic_api_key)
    if config.llm_backend == "openai":
        from .adapters.llm_openai import OpenAILLM

        if not config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY required for openai backend")
        return OpenAILLM(config.openai_api_key)
    if config.llm_backend == "grok":
        from .adapters.llm_grok import GrokLLM

        if not config.xai_api_key:
            raise RuntimeError("XAI_API_KEY required for grok backend")
        return GrokLLM(config.xai_api_key)
    if config.llm_backend == "auto":
        return _build_auto_llm(config)
    raise ValueError(f"unknown llm backend: {config.llm_backend}")


def _build_auto_llm(config: Config) -> LLMClient:
    """Routes calls to the best provider per task using model_hint.

    Builds a RoutedLLM across whichever provider keys are configured.
    Per-hint provider order is overrideable via env vars (see _AUTO_DEFAULTS)."""
    available: dict[str, LLMClient] = {}
    if config.anthropic_api_key:
        from .adapters.llm_anthropic import AnthropicLLM

        available["anthropic"] = AnthropicLLM(config.anthropic_api_key)
    if config.openai_api_key:
        from .adapters.llm_openai import OpenAILLM

        available["openai"] = OpenAILLM(config.openai_api_key)
    if config.xai_api_key:
        from .adapters.llm_grok import GrokLLM

        available["grok"] = GrokLLM(config.xai_api_key)

    if not available:
        raise RuntimeError(
            "BRACE_LLM_BACKEND=auto requires at least one of: "
            "ANTHROPIC_API_KEY, OPENAI_API_KEY, XAI_API_KEY"
        )

    routes: dict[str, list[tuple[str, LLMClient]]] = {}
    for hint, default_order in _AUTO_DEFAULTS.items():
        env_override = os.environ.get(f"BRACE_LLM_PREFERENCE_{hint.upper()}")
        order = (
            [p.strip() for p in env_override.split(",") if p.strip()]
            if env_override
            else default_order
        )
        routes[hint] = [(name, available[name]) for name in order if name in available]
        if not routes[hint]:
            # Preference list had no available providers — use any available.
            routes[hint] = list(available.items())

    from .adapters.llm_routed import RoutedLLM

    return RoutedLLM(routes)


def run_autopilot(
    config: Config | None = None,
    *,
    gmail: GmailClient | None = None,
    llm: LLMClient | None = None,
    memory: MemoryProvider | None = None,
    repo: Repository | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> AutoPilotRun:
    config = config or Config.from_env()
    configure_logging(config.log_level)

    gmail = gmail or _build_gmail(config)
    llm = llm or _build_llm(config)
    memory = memory or NullMemoryProvider()

    owns_repo = False
    if repo is None:
        repo = Repository(config.db_path)
        owns_repo = True
    try:
        runner = WorkflowRunner(
            workflow_name=WORKFLOW_NAME,
            seed_step=seed_step(),
            per_email_steps=per_email_steps(),
            gmail=gmail,
            llm=llm,
            memory=memory,
            repo=repo,
            mode=config.mode,
        )
        return runner.run(limit=config.limit, on_progress=on_progress)
    finally:
        if owns_repo:
            repo.close()
