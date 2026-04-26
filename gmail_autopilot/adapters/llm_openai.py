"""OpenAI-compatible LLM client.

Used directly for OpenAI's GPT models, and as a base for any other provider that
exposes an OpenAI-compatible chat-completions API (e.g. xAI's Grok via
`base_url="https://api.x.ai/v1"`)."""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ..errors import AuthError, PermanentError, TransientError, ValidationError

T = TypeVar("T", bound=BaseModel)


_OPENAI_MODEL_MAP = {
    "fast": "gpt-4o-mini",
    "smart": "gpt-4o",
    "cheap": "gpt-4o-mini",
}


class OpenAILLM:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        model_map: dict[str, str] | None = None,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise PermanentError("openai SDK not installed. Run: uv sync --extra openai") from e
        self._client = (
            OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        )
        self._model_map = model_map or _OPENAI_MODEL_MAP

    def complete(
        self,
        system: str,
        user: str,
        schema: type[T],
        model_hint: str = "fast",
    ) -> T:
        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
        )

        model = self._model_map.get(model_hint, self._model_map["fast"])
        instructions = (
            f"{system}\n\n"
            "Return ONLY a single JSON object matching this schema. "
            "No prose, no markdown fences.\n\n"
            f"Schema:\n{json.dumps(schema.model_json_schema())}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_tokens=2000,
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

        text = (resp.choices[0].message.content or "").strip()
        # Defensive: strip markdown fences if any provider includes them despite
        # response_format=json_object (some OpenAI-compatible servers do).
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
