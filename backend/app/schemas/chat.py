from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    # Anonymous id the browser keeps across conversations; Langfuse's user id. A UUID, so no
    # emails or names (PII) reach the traces through it.
    visitor_id: UUID | None = None
    # Hard cap at the HTTP layer; the max_length guardrail gives the friendly message.
    message: str = Field(min_length=1, max_length=10_000)


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID  # id of the assistant reply; send it back to rate the reply
    reply: str


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
