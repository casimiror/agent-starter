import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.domain.models import Conversation
from app.services.channel_conversations import ChannelConversations
from app.services.whatsapp_service import APOLOGY, SLOW_DOWN, TEXT_ONLY, WhatsAppService

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
USER = "whatsapp:+34600123456"
OURS = "whatsapp:+14155238886"
SECRET_TEXT = "my private question"


class FakeConversations:
    """Stateful: the conversation created by the first message is the latest for the sender."""

    def __init__(self, create_delay: float = 0) -> None:
        self.delay = create_delay
        self.conversations: list[Conversation] = []

    def latest_for_visitor(self, visitor_id, channel):
        return self.conversations[-1] if self.conversations else None

    def last_activity(self, conversation_id):
        return NOW

    def get_or_create(self, conversation_id, visitor_id=None, channel="web"):
        time.sleep(self.delay)  # widens the window in which two threads would both create
        conversation = Conversation(
            id=uuid4(), visitor_id=visitor_id, channel=channel, created_at=NOW
        )
        self.conversations.append(conversation)
        return conversation


class FakeChat:
    def __init__(self, reply="All good", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple] = []

    def handle_turn(self, conversation_id, user_text, visitor_id=None, channel="web"):
        self.calls.append((conversation_id, user_text, visitor_id, channel))
        if self.error:
            raise self.error
        return SimpleNamespace(reply=self.reply)


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to, from_, body):
        self.sent.append({"to": to, "from_": from_, "body": body})
        return "SM1"


def _build(chat=None, hit=lambda *_: True, conversations=None):
    repo = conversations or FakeConversations()
    channels = ChannelConversations(repo, "s3cret", timedelta(hours=24), lambda: NOW)
    chat = chat or FakeChat()
    sender = FakeSender()
    flushed: list[int] = []
    service = WhatsAppService(
        channels, chat, sender, "10/minute", hit, flush=lambda: flushed.append(1)
    )
    return service, chat, sender, repo, flushed


def _handle(service, body=SECRET_TEXT, num_media=0, sid="SM-in-1"):
    service.handle_message(USER, OURS, body, num_media, sid)


def test_a_normal_turn_sends_the_formatted_reply_from_the_number_written_to():
    service, chat, sender, _, flushed = _build(FakeChat("See [docs](https://a.example/d) **now**"))
    _handle(service)
    assert sender.sent == [
        {"to": USER, "from_": OURS, "body": "See docs: https://a.example/d *now*"}
    ]
    assert len(chat.calls) == 1
    assert chat.calls[0][1:] == (SECRET_TEXT, chat.calls[0][2], "whatsapp")
    assert flushed == [1]  # observability flushed after the turn


def test_a_long_reply_goes_out_as_several_messages_in_order():
    service, _, sender, _, _ = _build(FakeChat(" ".join(["word"] * 500)))
    _handle(service)
    assert len(sender.sent) == 2
    assert all(len(m["body"]) <= 1600 for m in sender.sent)


def test_media_gets_the_canned_message_and_no_turn():
    service, chat, sender, _, flushed = _build()
    _handle(service, num_media=1)
    assert [m["body"] for m in sender.sent] == [TEXT_ONLY]
    assert chat.calls == []
    assert flushed == [1]


def test_an_empty_body_gets_the_canned_message_and_no_turn():
    service, chat, sender, _, _ = _build()
    _handle(service, body="   ")
    assert [m["body"] for m in sender.sent] == [TEXT_ONLY]
    assert chat.calls == []


def test_over_the_limit_gets_a_polite_message_and_no_turn():
    seen: list[tuple] = []

    def hit(limit, channel, key):
        seen.append((limit, channel, key))
        return False

    service, chat, sender, _, _ = _build(hit=hit)
    _handle(service)
    assert [m["body"] for m in sender.sent] == [SLOW_DOWN]
    assert chat.calls == []
    assert seen[0][:2] == ("10/minute", "whatsapp")
    assert "600123456" not in seen[0][2]  # keyed by the anonymous id


def test_a_failing_turn_sends_an_apology_not_silence(caplog):
    service, chat, sender, _, flushed = _build(FakeChat(error=RuntimeError(SECRET_TEXT)))
    with caplog.at_level(logging.INFO):
        _handle(service)
    assert [m["body"] for m in sender.sent] == [APOLOGY]
    assert caplog.records[-1].error == "RuntimeError"
    assert SECRET_TEXT not in caplog.text
    assert flushed == [1]


def test_a_failure_outside_the_turn_still_apologises():
    def broken_limiter(*_):
        raise ConnectionError("redis down")

    service, chat, sender, _, flushed = _build(hit=broken_limiter)
    _handle(service)
    assert [m["body"] for m in sender.sent] == [APOLOGY]
    assert flushed == [1]


def test_the_phone_number_never_reaches_the_turn_the_logs_or_the_visitor_id(caplog):
    service, chat, _, _, _ = _build()
    with caplog.at_level(logging.DEBUG):
        _handle(service)
        _handle(service, num_media=1)
    conversation_id, text, visitor_id, channel = chat.calls[0]
    blob = f"{conversation_id} {text} {visitor_id} {channel}"
    assert "600123456" not in blob
    assert "600123456" not in caplog.text
    assert "34600" not in caplog.text
    visitor_logged = [r for r in caplog.records if hasattr(r, "visitor_id")]
    assert all(r.visitor_id == str(visitor_id) for r in visitor_logged)


def test_logs_carry_the_visitor_id_and_message_sid_and_no_text(caplog):
    service, *_ = _build(hit=lambda *_: False)
    with caplog.at_level(logging.INFO, logger="app.whatsapp"):
        _handle(service, sid="SM-abc")
    record = caplog.records[0]
    assert record.message_sid == "SM-abc"
    assert SECRET_TEXT not in caplog.text and "600123456" not in caplog.text


def test_two_concurrent_messages_from_one_sender_share_one_conversation():
    repo = FakeConversations(create_delay=0.05)
    service, chat, sender, _, _ = _build(conversations=repo)
    threads = [
        threading.Thread(target=_handle, args=(service,), kwargs={"sid": f"SM{i}"})
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(repo.conversations) == 1
    assert len({call[0] for call in chat.calls}) == 1
    assert len(chat.calls) == 2
    assert len(sender.sent) == 2
