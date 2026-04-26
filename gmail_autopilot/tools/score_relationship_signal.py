from __future__ import annotations

from pydantic import BaseModel

from ..models import ContactMemory, EmailSummary, RelationshipSignal
from .base import Tool, ToolContext


class ScoreInput(BaseModel):
    email: EmailSummary
    memory: ContactMemory | None = None


class ScoreOutput(BaseModel):
    signal: RelationshipSignal


_SYSTEM = (
    "You score whether an inbound email needs a reply from the recipient. "
    "Return JSON with: email_id (string), needs_reply (bool), confidence (0..1), "
    "and why_now (one short sentence explaining the relationship signal)."
)


class ScoreRelationshipSignal(Tool[ScoreInput, ScoreOutput]):
    name = "score_relationship_signal"
    input_schema = ScoreInput
    output_schema = ScoreOutput
    is_side_effect = False

    def execute(self, inp: ScoreInput, ctx: ToolContext) -> ScoreOutput:
        memory_block = ""
        if inp.memory:
            memory_block = (
                "\nContact memory:\n"
                f"- last_interaction_at: {inp.memory.last_interaction_at}\n"
                f"- relationship_strength: {inp.memory.relationship_strength}\n"
                f"- recent_signals: {inp.memory.recent_signals}\n"
            )
        user_prompt = (
            f"email_id: {inp.email.id}\n"
            f"thread_id: {inp.email.thread_id}\n"
            f"sender: {inp.email.sender.email}\n"
            f"subject: {inp.email.subject}\n"
            f"snippet: {inp.email.snippet}"
            f"{memory_block}"
        )
        signal = ctx.llm.complete(
            system=_SYSTEM,
            user=user_prompt,
            schema=RelationshipSignal,
            model_hint="fast",
        )
        # Pin email_id to authoritative value (LLMs sometimes hallucinate ids).
        if signal.email_id != inp.email.id:
            signal = signal.model_copy(update={"email_id": inp.email.id})
        return ScoreOutput(signal=signal)
