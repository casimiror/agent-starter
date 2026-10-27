"""Gate for the routes that belong to one `VOICE_MODE`.

Every mode's routes are registered; the ones of the mode that is not selected answer 404, so the
mode is read per request from the settings (tests and deployments change it without re-importing
modules). A new mode adds its router in `voice/__init__.py` and its entry in `INCOMING`
(`app/services/channels/voice/twiml.py`)."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings


def only(mode: str) -> Callable[..., None]:
    def check(settings: Annotated[Settings, Depends(get_settings)]) -> None:
        if settings.voice_mode != mode:
            raise HTTPException(status.HTTP_404_NOT_FOUND)

    return check
