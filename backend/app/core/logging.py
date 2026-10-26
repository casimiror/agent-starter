"""Structured logs on stdout: one JSON object per line, which Vercel and Docker collect as is.

Log with `extra` for fields, never by formatting values into the message:

    log.info("chat turn", extra={"conversation_id": str(cid), "latency_ms": 812})

Every record carries the request id of the HTTP request it belongs to (`request_id_var`, set by
the access-log middleware in app/main.py). Never log user text or personal data: emails that slip
into a message or a field are masked anyway.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# Attributes every LogRecord has: anything else on a record came from `extra`.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "request_id"}
# Libraries that log every HTTP call or request at INFO; our access log covers requests.
_NOISY = ("httpx", "httpx2", "httpcore", "openai", "anthropic", "uvicorn.access")


def _mask(value: Any) -> Any:
    return _EMAIL.sub("[email]", value) if isinstance(value, str) else value


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    return {k: _mask(v) for k, v in vars(record).items() if k not in _STANDARD}


class _RequestId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": _mask(record.getMessage()),
        }
        if getattr(record, "request_id", None):
            entry["request_id"] = record.request_id
        entry.update(_fields(record))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """For a local terminal: `time LEVEL logger [request] message key=value ...`."""

    def format(self, record: logging.LogRecord) -> str:
        fields = " ".join(f"{k}={v}" for k, v in _fields(record).items())
        line = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}"
        if getattr(record, "request_id", None):
            line += f" [{record.request_id[:8]}]"
        line += f" {_mask(record.getMessage())}" + (f" {fields}" if fields else "")
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(settings: Settings) -> None:
    """Idempotent: replaces the root handlers, so calling it again (tests, reloads) is safe."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestId())
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
