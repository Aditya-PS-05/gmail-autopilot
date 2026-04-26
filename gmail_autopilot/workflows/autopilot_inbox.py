"""The canonical AutoPilot Inbox workflow.

Branch logic:
  score_relationship_signal -> if needs_reply == False, the next three steps
  are skipped (their `condition` closures return False).
"""

from __future__ import annotations

from ..engine.step import Step
from ..tools.create_draft import CreateDraft, CreateDraftInput
from ..tools.generate_draft import GenerateDraft, GenerateDraftInput
from ..tools.list_recent_emails import ListInput, ListRecentEmails
from ..tools.read_thread import ReadThread, ReadThreadInput
from ..tools.score_relationship_signal import ScoreInput, ScoreRelationshipSignal

WORKFLOW_NAME = "autopilot_inbox"


def seed_step() -> Step:
    return Step(
        name="list_recent_emails",
        tool=ListRecentEmails(),
        output_key="seed",
        input_builder=lambda state: ListInput(limit=state.get("limit", 10)),
    )


def per_email_steps() -> list[Step]:
    needs_reply = lambda s: s["signal_out"].signal.needs_reply

    return [
        Step(
            name="score_relationship_signal",
            tool=ScoreRelationshipSignal(),
            output_key="signal_out",
            input_builder=lambda s: ScoreInput(
                email=s["email"],
                memory=s.get("memory"),
            ),
        ),
        Step(
            name="read_thread",
            tool=ReadThread(),
            output_key="thread_out",
            input_builder=lambda s: ReadThreadInput(thread_id=s["email"].thread_id),
            condition=needs_reply,
        ),
        Step(
            name="generate_draft",
            tool=GenerateDraft(),
            output_key="draft_out",
            input_builder=lambda s: GenerateDraftInput(
                thread=s["thread_out"].thread,
                signal=s["signal_out"].signal,
                memory=s.get("memory"),
            ),
            condition=needs_reply,
        ),
        Step(
            name="create_draft",
            tool=CreateDraft(),
            output_key="created_out",
            input_builder=lambda s: CreateDraftInput(draft=s["draft_out"].draft),
            condition=needs_reply,
        ),
    ]
