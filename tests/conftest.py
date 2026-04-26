import os
import tempfile
from pathlib import Path

import pytest

os.environ["BRACE_RETRY_NO_SLEEP"] = "1"

from gmail_autopilot.adapters.gmail_mock import MockGmailClient
from gmail_autopilot.adapters.llm_fake import FakeLLMClient
from gmail_autopilot.adapters.memory_null import NullMemoryProvider
from gmail_autopilot.state.repository import Repository


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = Repository(Path(path))
    yield repo
    repo.close()
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def mock_gmail():
    return MockGmailClient()


@pytest.fixture
def fake_llm():
    return FakeLLMClient()


@pytest.fixture
def null_memory():
    return NullMemoryProvider()
