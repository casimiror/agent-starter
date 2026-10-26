import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import access_log
from app.core.config import Settings
from app.core.logging import JsonFormatter, configure_logging, request_id_var


def _record(msg: str, **extra) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "app.test", "levelname": "INFO", "msg": msg, **extra})
    record.request_id = request_id_var.get()
    return record


def test_json_lines_carry_fields_and_request_id():
    token = request_id_var.set("req-1")
    try:
        line = JsonFormatter().format(_record("chat turn", latency_ms=812, tools_called=["x"]))
    finally:
        request_id_var.reset(token)
    entry = json.loads(line)
    assert entry["msg"] == "chat turn" and entry["request_id"] == "req-1"
    assert entry["latency_ms"] == 812 and entry["tools_called"] == ["x"]


def test_emails_are_masked_in_messages_and_fields():
    entry = json.loads(JsonFormatter().format(_record("from ana@acme.com", user="b.c@x.io")))
    assert entry["msg"] == "from [email]" and entry["user"] == "[email]"


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(access_log)

    @app.get("/api/ping")
    def ping() -> dict:
        logging.getLogger("app.test").info("inside", extra={"step": 1})
        return {"ok": True}

    return app


def test_access_log_returns_the_request_id_and_logs_the_request(capsys):
    configure_logging(Settings(_env_file=None, log_format="json"))
    response = TestClient(_app()).get("/api/ping", headers={"x-request-id": "abc"})

    assert response.headers["x-request-id"] == "abc"
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    inside = next(e for e in lines if e["logger"] == "app.test")
    request = next(e for e in lines if e["logger"] == "app.access")
    assert inside["request_id"] == "abc" and inside["step"] == 1
    assert request["path"] == "/api/ping" and request["status"] == 200
    assert "duration_ms" in request
