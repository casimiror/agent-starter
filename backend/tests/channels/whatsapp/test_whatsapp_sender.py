import logging
from types import SimpleNamespace

import requests
from twilio.base.exceptions import TwilioRestException

from app.clients.whatsapp_sender import WhatsAppSender

TO = "whatsapp:+34600123456"
FROM = "whatsapp:+14155238886"


class FakeMessages:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(sid="SM123")


def _sender(error: Exception | None = None) -> tuple[WhatsAppSender, FakeMessages]:
    messages = FakeMessages(error)
    return WhatsAppSender(SimpleNamespace(messages=messages)), messages


def test_send_passes_the_numbers_and_body_and_returns_the_sid():
    sender, messages = _sender()
    assert sender.send(to=TO, from_=FROM, body="hi") == "SM123"
    assert messages.calls == [{"to": TO, "from_": FROM, "body": "hi"}]


def test_a_twilio_error_is_swallowed_and_logged_with_its_code_only(caplog):
    error = TwilioRestException(
        400, "/Messages", msg=f"Unable to create record: {TO} is not a valid number", code=21211
    )
    sender, _ = _sender(error)
    with caplog.at_level(logging.ERROR, logger="app.whatsapp"):
        assert sender.send(to=TO, from_=FROM, body="secret reply") is None
    record = caplog.records[0]
    assert (record.twilio_code, record.status) == (21211, 400)
    assert "600123456" not in caplog.text
    assert "secret reply" not in caplog.text


def test_a_network_error_is_swallowed_and_logged_by_type(caplog):
    sender, _ = _sender(requests.ConnectionError(f"cannot reach host for {TO}"))
    with caplog.at_level(logging.ERROR, logger="app.whatsapp"):
        assert sender.send(to=TO, from_=FROM, body="hi") is None
    assert caplog.records[0].error == "ConnectionError"
    assert "600123456" not in caplog.text


def test_an_unexpected_error_is_not_hidden():
    sender, _ = _sender(ValueError("bug"))
    try:
        sender.send(to=TO, from_=FROM, body="hi")
    except ValueError:
        return
    raise AssertionError("only Twilio and network errors are caught")
