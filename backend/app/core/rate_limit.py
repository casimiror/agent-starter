from functools import lru_cache

import limits
from fastapi import Request
from limits import RateLimitItem
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings


def client_ip(request: Request) -> str:
    """Rate-limit key. On Vercel the platform sets x-real-ip to the caller's IP (and overwrites
    any client-sent value); elsewhere trust only the socket, so the header can't be spoofed.
    Run uvicorn with --proxy-headers when behind another proxy."""
    if get_settings().serverless and (ip := request.headers.get("x-real-ip")):
        return ip
    return get_remote_address(request)


# Per-IP limits protect the shared LLM API key. With the default memory:// storage each Vercel
# instance counts separately; RATE_LIMIT_STORAGE_URI (Redis) makes the limit global.
limiter = Limiter(key_func=client_ip, storage_uri=get_settings().rate_limit_storage_uri)


@lru_cache
def _parse(limit: str) -> RateLimitItem:
    return limits.parse(limit)


def hit_sender(limit: str, channel: str, key: str) -> bool:
    """Count one message from a non-web sender; False means over `limit` ("20/minute").

    Webhooks all come from the provider's IPs, so the per-IP limit above can't tell senders apart.
    Callers pass the anonymous visitor id as `key`, never a phone number. Uses the limiter's own
    storage and strategy (`RATE_LIMIT_STORAGE_URI`), so a Redis URL makes it global, and follows
    its `enabled` flag (tests switch it off).
    """
    if not limiter.enabled:
        return True
    return limiter._limiter.hit(_parse(limit), "sender", channel, key)
