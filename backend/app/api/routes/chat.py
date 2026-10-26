from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.deps import get_chat_service
from app.core import observability
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(lambda: get_settings().rate_limit_chat)
def chat(
    request: Request,  # required by slowapi
    body: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
    background: BackgroundTasks,
) -> ChatResponse:
    result = service.handle_turn(body.conversation_id, body.message, body.visitor_id)
    # Serverless instances may freeze after the response: send this turn's trace now, after the
    # reply is on its way, instead of relying on the exporter's background thread.
    background.add_task(observability.flush)
    return ChatResponse(
        conversation_id=result.conversation_id, message_id=result.message_id, reply=result.reply
    )
