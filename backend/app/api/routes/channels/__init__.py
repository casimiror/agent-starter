"""Routers of the non-web channels (docs/channels.md), mounted only when CHANNELS enables them.

Each channel registers a loader that imports its router on demand, so a deployment that doesn't
use WhatsApp or voice never imports their code or their dependencies. `/api/chat` (web) is not
here: it is always mounted.
"""

import importlib
import logging
from collections.abc import Callable, Mapping

from fastapi import APIRouter, FastAPI

from app.core.config import Settings

log = logging.getLogger("app.channels")

RouterLoader = Callable[[], APIRouter]


def _lazy(module: str) -> RouterLoader:
    return lambda: importlib.import_module(module).router


# channel name -> loader of its router. A channel PR adds its line here.
CHANNEL_ROUTERS: dict[str, RouterLoader] = {}


def include_channel_routers(
    app: FastAPI, settings: Settings, registry: Mapping[str, RouterLoader] | None = None
) -> list[str]:
    """Mount the router of every enabled channel; returns the names mounted."""
    registry = CHANNEL_ROUTERS if registry is None else registry
    mounted = []
    for name in settings.extra_channels:
        if name not in registry:
            # Enabled but nothing to mount: say so instead of silently serving no webhook.
            log.warning("channel enabled but not available", extra={"channel": name})
            continue
        app.include_router(registry[name](), prefix="/api")
        mounted.append(name)
    return mounted
