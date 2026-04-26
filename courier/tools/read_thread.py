from __future__ import annotations

from pydantic import BaseModel

from ..models import Thread
from .base import Tool, ToolContext


class ReadThreadInput(BaseModel):
    thread_id: str


class ReadThreadOutput(BaseModel):
    thread: Thread


class ReadThread(Tool[ReadThreadInput, ReadThreadOutput]):
    name = "read_thread"
    input_schema = ReadThreadInput
    output_schema = ReadThreadOutput
    is_side_effect = False

    def execute(self, inp: ReadThreadInput, ctx: ToolContext) -> ReadThreadOutput:
        return ReadThreadOutput(thread=ctx.gmail.read_thread(inp.thread_id))
