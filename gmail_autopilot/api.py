"""Public library entrypoint. The CLI is a thin wrapper around `run_autopilot`.

Every dependency is injectable so callers (tests, brace's backend) can plug in
their own gmail / llm / memory provider without changing the engine."""

from __future__ import annotations

from .adapters.gmail_base import GmailClient
from .adapters.gmail_mock import MockGmailClient
from .adapters.llm_base import LLMClient
from .adapters.llm_fake import FakeLLMClient
from .adapters.memory_base import MemoryProvider
from .adapters.memory_null import NullMemoryProvider
from .config import Config
from .engine.runner import WorkflowRunner
from .models import AutoPilotRun
from .reliability.logger import configure_logging
from .state.repository import Repository
from .workflows.autopilot_inbox import WORKFLOW_NAME, per_email_steps, seed_step


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
    raise ValueError(f"unknown llm backend: {config.llm_backend}")


def run_autopilot(
    config: Config | None = None,
    *,
    gmail: GmailClient | None = None,
    llm: LLMClient | None = None,
    memory: MemoryProvider | None = None,
    repo: Repository | None = None,
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
        return runner.run(limit=config.limit)
    finally:
        if owns_repo:
            repo.close()
