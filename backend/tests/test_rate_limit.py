import pytest
from starlette.requests import Request

from app.core import rate_limit
from app.core.config import Settings


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": ("10.0.0.1", 1234)})


@pytest.mark.parametrize(("serverless", "expected"), [(True, "203.0.113.7"), (False, "10.0.0.1")])
def test_client_ip_trusts_x_real_ip_only_on_vercel(monkeypatch, serverless, expected):
    settings = Settings(_env_file=None, serverless=serverless)
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    assert rate_limit.client_ip(_request({"x-real-ip": "203.0.113.7"})) == expected


def test_client_ip_falls_back_to_socket_without_header(monkeypatch):
    settings = Settings(_env_file=None, serverless=True)
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    assert rate_limit.client_ip(_request({})) == "10.0.0.1"
