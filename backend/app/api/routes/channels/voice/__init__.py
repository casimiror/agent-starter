"""Twilio voice channel router: `/incoming` (common to every `VOICE_MODE`) plus the routes of each
mode (relay, gather, realtime). Only the router is exposed; `incoming.py` has the shared part."""

from fastapi import APIRouter

from app.api.routes.channels.voice import gather, incoming, realtime, relay

router = APIRouter(tags=["voice"])
router.include_router(incoming.router)
router.include_router(relay.router)
router.include_router(gather.router)
router.include_router(realtime.router)
