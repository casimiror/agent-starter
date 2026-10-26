from fastapi import Request
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


# Per-IP limits protect the shared LLM API key. In-memory storage: on Vercel each function
# instance counts separately, so the limit is per instance (see README > Deploy).
limiter = Limiter(key_func=client_ip)
