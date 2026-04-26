"""Provider-agnostic LLM client.

Brace's stack routes across Gemini, Claude, and GPT, so this Protocol takes a
`model_hint` string ("fast" / "smart" / "cheap") that each adapter maps to a
concrete model id of its choice."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    def complete(
        self,
        system: str,
        user: str,
        schema: type[T],
        model_hint: str = "fast",
    ) -> T: ...
