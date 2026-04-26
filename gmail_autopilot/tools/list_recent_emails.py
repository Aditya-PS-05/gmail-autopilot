from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import EmailSummary
from .base import Tool, ToolContext


class ListInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)


class ListOutput(BaseModel):
    emails: list[EmailSummary]


class ListRecentEmails(Tool[ListInput, ListOutput]):
    name = "list_recent_emails"
    input_schema = ListInput
    output_schema = ListOutput
    is_side_effect = False

    def execute(self, inp: ListInput, ctx: ToolContext) -> ListOutput:
        return ListOutput(emails=ctx.gmail.list_recent_emails(limit=inp.limit))
