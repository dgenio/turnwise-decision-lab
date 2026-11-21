"""The typed final answer of a native agent whose citations the host checks (arm S, pydantic).

It changes only the agent's *final output type*: the loop, the tools and the instructions are untouched. The
field descriptions are the only prompt text it adds. It is not a Turnwise step and cannot propose anything.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class CitedAnswer(BaseModel):
    text: str = Field(description="The answer for the user.")
    cited_receipts: List[str] = Field(
        description="Ids of the host tool receipts the answer relies on (the 'receipt' field of tool results).")
