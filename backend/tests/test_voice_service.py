import logging
from uuid import uuid4

from app.services.voice_service import APOLOGY, NO_ANSWER
from tests.voice_fakes import CALLER, FakeChat, make_voice


def test_every_call_is_a_new_voice_conversation_for_the_hashed_caller():
    voice = make_voice()
    first = voice.service.start_call(CALLER, "CA1")
    second = voice.service.start_call(CALLER, "CA2")

    assert first.conversation_id != second.conversation_id  # no 24 h reuse
    assert first.visitor_id == second.visitor_id == voice.channels.visitor_id(CALLER)
    assert CALLER not in str(first.visitor_id)
    assert {row.channel for row in voice.repo.rows.values()} == {"voice"}


def test_a_caller_over_the_limit_is_refused_and_no_conversation_is_created():
    seen: list[tuple] = []

    def over(limit, channel, key):
        seen.append((limit, channel, key))
        return False

    voice = make_voice(hit=over, rate_limit="3/hour")
    assert voice.service.start_call(CALLER, "CA1") is None
    assert voice.repo.rows == {}
    limit, channel, key = seen[0]
    assert (limit, channel) == ("3/hour", "voice")
    assert key == str(voice.channels.visitor_id(CALLER))  # the anonymous id, not the number


def test_answer_runs_a_voice_turn_and_formats_the_reply_for_speech():
    chat = FakeChat("**Hello** there, see [docs](https://a.example/d)")
    voice = make_voice(chat)
    call = voice.service.start_call(CALLER, "CA1")

    spoken = voice.service.answer(call, "what do you do", "CA1")

    assert spoken == "Hello there, see docs No links aloud."
    assert chat.calls == [(call.conversation_id, "what do you do", call.visitor_id, "voice")]
    assert voice.flushed == [1]


def test_a_failing_turn_is_a_spoken_apology_logging_only_the_error_type(caplog):
    chat = FakeChat(error=RuntimeError("secret words the caller said"))
    voice = make_voice(chat)
    call = voice.service.start_call(CALLER, "CA1")

    with caplog.at_level(logging.INFO):
        spoken = voice.service.answer(call, "private question", "CA1")

    assert spoken == APOLOGY
    assert voice.flushed == [1]
    record = next(r for r in caplog.records if r.message == "voice turn failed")
    assert record.error == "RuntimeError"
    assert "secret words" not in caplog.text and "private question" not in caplog.text


def test_an_empty_reply_is_not_silence():
    voice = make_voice(FakeChat("   "))
    call = voice.service.start_call(CALLER, "CA1")
    assert voice.service.answer(call, "hi") == NO_ANSWER


def test_find_call_only_finds_voice_conversations_that_exist():
    voice = make_voice()
    call = voice.service.start_call(CALLER, "CA1")
    web = voice.repo.get_or_create(None, uuid4(), "web")

    found = voice.service.find_call(call.conversation_id)
    assert found.conversation_id == call.conversation_id
    assert found.visitor_id == call.visitor_id
    assert voice.service.find_call(web.id) is None
    assert voice.service.find_call(uuid4()) is None


def test_over_time_follows_the_injected_clock():
    voice = make_voice(max_call_seconds=60)
    call = voice.service.start_call(CALLER, "CA1")
    assert not voice.service.over_time(call)
    voice.clock.elapsed = 59
    assert not voice.service.over_time(call)
    voice.clock.elapsed = 60
    assert voice.service.over_time(call)


def test_the_caller_number_never_reaches_logs_or_the_agent(caplog):
    chat = FakeChat()
    voice = make_voice(chat)
    with caplog.at_level(logging.DEBUG):
        call = voice.service.start_call(CALLER, "CA1")
        voice.service.answer(call, "hello", "CA1")
        voice.service.start_call(CALLER, "CA2")

    assert "600123456" not in caplog.text
    assert "600123456" not in repr(chat.calls)
    assert "600123456" not in repr(voice.repo.rows)
    started = next(r for r in caplog.records if r.message == "voice call started")
    assert started.visitor_id == str(call.visitor_id) and started.call_sid == "CA1"
