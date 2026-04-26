"""Anthropic Claude LLM client. Returns typed Pydantic objects via JSON mode."""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ..errors import AuthError, PermanentError, TransientError, ValidationError

T = TypeVar("T", bound=BaseModel)


_MODEL_MAP = {
    "fast": "claude-haiku-4-5-20251001",
    "smart": "claude-sonnet-4-6",
    "cheap": "claude-haiku-4-5-20251001",
}


class AnthropicLLM:
    def __init__(self, api_key: str):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise PermanentError(
                "anthropic SDK not installed. Run: uv sync --extra anthropic"
            ) from e
        self._client = Anthropic(api_key=api_key)

    def complete(
        self,
        system: str,
        user: str,
        schema: type[T],
        model_hint: str = "fast",
    ) -> T:
        from anthropic import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
        )

        model = _MODEL_MAP.get(model_hint, _MODEL_MAP["fast"])
        instructions = (
            f"{system}\n\n"
            "Return ONLY a single JSON object matching this schema. "
            "No prose, no markdown fences.\n\n"
            f"Schema:\n{json.dumps(schema.model_json_schema())}"
        )
        try:
            resp = self._client.messages.create(
                model=model,
                max_tokens=2000,
                system=instructions,
                messages=[{"role": "user", "content": user}],
            )
        except AuthenticationError as e:
            raise AuthError(str(e)) from e
        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            raise TransientError(str(e)) from e
        except APIError as e:
            status = getattr(e, "status_code", 0) or 0
            if 500 <= status < 600:
                raise TransientError(str(e)) from e
            raise PermanentError(str(e)) from e

        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValidationError(f"LLM did not return valid JSON: {e}; text={text[:200]!r}") from e
        try:
            return schema.model_validate(data)
        except PydanticValidationError as e:
            raise ValidationError(f"LLM output did not match schema {schema.__name__}: {e}") from e
