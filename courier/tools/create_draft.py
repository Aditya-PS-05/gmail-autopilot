"""The only side-effect tool. Idempotency-checked."""

from __future__ import annotations

from pydantic import BaseModel

from ..models import CreatedDraft, DraftContent
from ..reliability.idempotency import draft_idempotency_key
from .base import Tool, ToolContext


class CreateDraftInput(BaseModel):
    draft: DraftContent


class CreateDraftOutput(BaseModel):
    created: CreatedDraft


class CreateDraft(Tool[CreateDraftInput, CreateDraftOutput]):
    name = "create_draft"
    input_schema = CreateDraftInput
    output_schema = CreateDraftOutput
    is_side_effect = True
    is_idempotent = True  # via the idempotency_keys table

    def execute(self, inp: CreateDraftInput, ctx: ToolContext) -> CreateDraftOutput:
        key = draft_idempotency_key(ctx.workflow_name, inp.draft.thread_id, inp.draft.body)

        existing = ctx.repo.lookup_idempotency(key)
        if existing:
            return CreateDraftOutput(
                created=CreatedDraft(
                    draft_id=existing,
                    thread_id=inp.draft.thread_id,
                    was_idempotent_hit=True,
                ),
            )

        created = ctx.gmail.create_draft(
            thread_id=inp.draft.thread_id,
            subject=inp.draft.subject,
            body=inp.draft.body,
        )
        # NOTE: there is a narrow window where Gmail succeeds but the local DB
        # write below fails. On re-run the same content would be created again.
        # Acceptable for "basic idempotency"; a 2-phase commit (record-pending,
        # then commit) would close it if the assignment escalates.
        ctx.repo.record_idempotency(
            key=key,
            workflow=ctx.workflow_name,
            thread_id=inp.draft.thread_id,
            draft_id=created.draft_id,
            workflow_run_id=ctx.workflow_run_id,
        )
        return CreateDraftOutput(created=created)
