"""Tool interface. Every workflow primitive has typed input/output, plus an
explicit `is_side_effect` flag — that flag is what makes dry-run mode trivial."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..adapters.gmail_base import GmailClient
    from ..adapters.llm_base import LLMClient
    from ..adapters.memory_base import MemoryProvider
    from ..state.repository import Repository

In = TypeVar("In", bound=BaseModel)
Out = TypeVar("Out", bound=BaseModel)


@dataclass
class ToolContext:
    workflow_name: str
    workflow_run_id: str
    mode: str  # "dry-run" | "real"
    gmail: GmailClient
    llm: LLMClient
    memory: MemoryProvider
    repo: Repository
    email_run_id: str | None = None


class Tool(ABC, Generic[In, Out]):
    name: str
    is_side_effect: bool = False
    is_idempotent: bool = True

    input_schema: type[In]
    output_schema: type[Out]

    @abstractmethod
    def execute(self, inp: In, ctx: ToolContext) -> Out: ...

    def hash_input(self, inp: In) -> str:
        return hashlib.sha256(
            json.dumps(inp.model_dump(mode="json"), sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
