from tests.test_voice_incoming import FORM, make_client, parse, post
from tests.voice_fakes import BASE, CALLER, CALLER_NAME


def test_realtime_connects_the_call_to_a_media_stream():
    client, voice, _ = make_client("realtime")
    response = post(client)
    root = parse(response)
    (row,) = voice.repo.rows.values()

    stream = root.find("Connect/Stream")
    # wss, the same host as PUBLIC_BASE_URL and no query string: Twilio rejects one.
    assert stream.get("url") == "wss://bot.example.com/api/channels/voice/stream"
    parameters = {p.get("name"): p.get("value") for p in stream.findall("Parameter")}
    assert parameters == {"conversation_id": str(row.id)}
    assert [child.tag for child in root] == ["Connect"]
    assert row.channel == "voice"


def test_the_realtime_twiml_holds_no_personal_data():
    client, _, _ = make_client("realtime")
    text = post(client).text
    for personal in ("600123456", CALLER, CALLER_NAME, "Jane", "4155238886"):
        assert personal not in text


def test_each_realtime_call_is_a_new_conversation():
    client, voice, _ = make_client("realtime")
    post(client)
    post(client, {**FORM, "CallSid": "CA2"})
    assert len(voice.repo.rows) == 2


def test_a_realtime_caller_over_the_limit_is_hung_up():
    client, voice, _ = make_client("realtime", hit=lambda *_: False)
    root = parse(post(client))
    assert [child.tag for child in root] == ["Say", "Hangup"]
    assert voice.repo.rows == {}


def test_a_trailing_slash_in_the_base_url_does_not_double_up():
    client, _, _ = make_client("realtime", public_base_url=BASE + "/")
    stream = parse(post(client)).find("Connect/Stream")
    assert stream.get("url") == "wss://bot.example.com/api/channels/voice/stream"
