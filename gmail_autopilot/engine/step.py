from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..tools.base import Tool


@dataclass
class Step:
    """A node in the per-email pipeline.

    - input_builder: closure from current state-dict to a tool input model
    - condition:     optional closure from state-dict to bool; skipped when False
    - output_key:    where to put the tool's output in the state-dict
    - max_attempts:  retry budget (only TransientError counts)
    """

    name: str
    tool: Tool
    output_key: str
    input_builder: Callable[[dict[str, Any]], Any]
    condition: Callable[[dict[str, Any]], bool] | None = None
    max_attempts: int = 3
