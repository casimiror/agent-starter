import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from app.core.logging import request_id_var

log = logging.getLogger("app.access")


async def access_log(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """One log line per API request, and a request id on every log line it produces.

    The id comes from the caller's `x-request-id` (or a new one) and is returned in the response
    header, so a user-reported error can be found in the logs."""
    if not request.url.path.startswith("/api/"):
        return await call_next(request)  # static files: the CDN or Vite serves them in practice
    token = request_id_var.set(request.headers.get("x-request-id") or uuid4().hex)
    started = time.perf_counter()
    fields = {"method": request.method, "path": request.url.path}
    try:
        response = await call_next(request)
        status = response.status_code
        level = logging.WARNING if status >= 400 else logging.INFO
        log.log(level, "request", extra={**fields, "status": status, **_elapsed(started)})
        response.headers["x-request-id"] = request_id_var.get() or ""
        return response
    except Exception:
        log.exception("request failed", extra={**fields, "status": 500, **_elapsed(started)})
        raise
    finally:
        request_id_var.reset(token)


def _elapsed(started: float) -> dict[str, int]:
    return {"duration_ms": round((time.perf_counter() - started) * 1000)}
