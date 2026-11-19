"""The typed result of ONE model call under Turnwise control (pydantic, for framework structured output).

Both framework adapters ask the model for exactly this object. It cannot
execute anything: a ``tool_proposal`` is data that goes back to the policy.
Every field is required (nullable where unused) so the schema also works with
strict structured-output modes.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class StepOutcome(BaseModel):
    kind: Literal["answer_candidate", "tool_proposal", "needs_evidence"] = Field(
        description="answer_candidate, tool_proposal or needs_evidence")
    text: str = Field(description="The answer, the reason for the proposal, or what evidence is missing.")
    tool: Optional[str] = Field(description="tool_proposal only: one name from tools_you_may_propose; else null.")
    arguments_json: Optional[str] = Field(
        description="tool_proposal only: the tool arguments as a JSON object string; else null.")
    cited_receipts: List[str] = Field(description="answer_candidate: the receipt ids the answer relies on.")
