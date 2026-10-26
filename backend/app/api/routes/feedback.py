from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_feedback_service
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.schemas.chat import FeedbackRequest
from app.services.feedback_service import FeedbackService, MessageNotRateableError

router = APIRouter(tags=["feedback"])

Service = Annotated[FeedbackService, Depends(get_feedback_service)]
NOT_RATEABLE = "Only the assistant's replies can be rated."


@router.put("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(lambda: get_settings().rate_limit_feedback)
def rate_message(
    request: Request,  # required by slowapi
    message_id: UUID,
    body: FeedbackRequest,
    service: Service,
) -> None:
    try:
        service.rate(message_id, body.rating)
    except MessageNotRateableError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_RATEABLE) from None


@router.delete("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(lambda: get_settings().rate_limit_feedback)
def clear_message_rating(
    request: Request,  # required by slowapi
    message_id: UUID,
    service: Service,
) -> None:
    try:
        service.clear(message_id)
    except MessageNotRateableError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_RATEABLE) from None
