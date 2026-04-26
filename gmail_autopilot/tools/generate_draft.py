from __future__ import annotations

import re

from pydantic import BaseModel

from ..errors import ValidationError
from ..models import ContactMemory, DraftContent, RelationshipSignal, Thread
from .base import Tool, ToolContext


class GenerateDraftInput(BaseModel):
    thread: Thread
    signal: RelationshipSignal
    memory: ContactMemory | None = None


class GenerateDraftOutput(BaseModel):
    draft: DraftContent


_SYSTEM = (
    "You draft a short, polite reply to an email thread. "
    "Output JSON with: thread_id (string), subject (start with 'Re: '), "
    "body (1-3 short paragraphs, end with 'Best,'). "
    "Do not include HTML, scripts, or external links. Stay grounded in thread content."
)

_FORBIDDEN = (
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
)


class GenerateDraft(Tool[GenerateDraftInput, GenerateDraftOutput]):
    name = "generate_draft"
    input_schema = GenerateDraftInput
    output_schema = GenerateDraftOutput
    is_side_effect = False

    def execute(self, inp: GenerateDraftInput, ctx: ToolContext) -> GenerateDraftOutput:
        if not inp.thread.messages:
            raise ValidationError("thread has no messages")
        last = inp.thread.messages[-1]

        memory_block = ""
        if inp.memory and inp.memory.prior_thread_summary:
            memory_block = f"\nPrior context: {inp.memory.prior_thread_summary}"

        user_prompt = (
            f"thread_id: {inp.thread.id}\n"
            f"subject: {last.subject}\n"
            f"sender: {last.sender.email}\n"
            f"why_now: {inp.signal.why_now}\n"
            f"latest_message:\n{last.body[:2000]}"
            f"{memory_block}\n\n"
            f"Draft a reply."
        )
        draft = ctx.llm.complete(
            system=_SYSTEM,
            user=user_prompt,
            schema=DraftContent,
            model_hint="smart",
        )

        # Authoritative thread_id pin
        if draft.thread_id != inp.thread.id:
            draft = draft.model_copy(update={"thread_id": inp.thread.id})

        # Defensive validation: never let unsafe content through
        for pattern in _FORBIDDEN:
            if pattern.search(draft.body) or pattern.search(draft.subject):
                raise ValidationError("draft contains forbidden content (script/javascript)")
        if not draft.subject.lower().startswith("re:"):
            draft = draft.model_copy(update={"subject": f"Re: {draft.subject}"})

        return GenerateDraftOutput(draft=draft)
