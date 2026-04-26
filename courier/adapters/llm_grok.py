"""xAI Grok LLM client.

xAI's API is OpenAI-compatible, so Grok is just OpenAILLM pointed at xAI's
endpoint with Grok-flavored model ids. Uses the same `openai` SDK under the
hood — install with `uv sync --extra openai`."""

from __future__ import annotations

from .llm_openai import OpenAILLM

_GROK_MODEL_MAP = {
    "fast": "grok-3-mini",
    "smart": "grok-3",
    "cheap": "grok-3-mini",
}


class GrokLLM(OpenAILLM):
    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            model_map=_GROK_MODEL_MAP,
        )
