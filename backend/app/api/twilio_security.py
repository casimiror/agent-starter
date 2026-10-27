"""What every Twilio-facing route does before trusting a request: bound the body, then verify
`X-Twilio-Signature` against the public URL we told Twilio to call (never `request.url`: a proxy
or the ngrok tunnel rewrites the scheme and host we see)."""

import logging
from urllib.parse import parse_qsl, urlparse

from fastapi import HTTPException, Request, status
from twilio.request_validator import RequestValidator

from app.core.config import Settings

log = logging.getLogger("app.twilio")

# Twilio's form is a few hundred bytes; this only stops a flood of junk before it is parsed.
MAX_BODY_BYTES = 64 * 1024


def public_url(settings: Settings, path: str) -> str:
    """The https URL Twilio calls for `path` (which may carry a query string)."""
    return settings.public_base_url.rstrip("/") + path


def websocket_url(settings: Settings, path: str) -> str:
    """The wss URL for `path`: same host as PUBLIC_BASE_URL."""
    return "wss://" + urlparse(settings.public_base_url).netloc + path


async def read_body(request: Request) -> bytes:
    """The request body, refusing anything over MAX_BODY_BYTES with 413: by Content-Length when
    sent, and while streaming when it is not (chunked uploads, or a lying header)."""
    too_large = HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Body too large")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise too_large
    return bytes(body)


async def verified_form(
    request: Request, settings: Settings, url: str, channel: str
) -> dict[str, str]:
    """The form fields of a Twilio webhook whose signature matches `url`: 413 for a big body, 403
    for a bad or missing signature. The fields are personal data: callers must not log them."""
    body = await read_body(request)
    params = dict(parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True))
    signature = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(settings.twilio_auth_token).validate(url, params, signature):
        log.warning("webhook with an invalid signature", extra={"channel": channel})
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    return params


def handshake_valid(settings: Settings, url: str, signature: str) -> bool:
    """A WebSocket handshake has no body, so the signature covers the URL alone. Twilio's docs do
    not say whether it signs the URL with or without a trailing slash: accept both."""
    validator = RequestValidator(settings.twilio_auth_token)
    return any(validator.validate(candidate, {}, signature) for candidate in (url, url + "/"))
