import re

from app.services.whatsapp_format import (
    ELLIPSIS,
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    format_for_whatsapp,
    split_for_whatsapp,
    to_whatsapp_markup,
)

URL = re.compile(r"https?://\S+")


def test_markdown_link_becomes_text_and_url():
    assert (
        to_whatsapp_markup("See [our docs](https://example.com/docs) now")
        == "See our docs: https://example.com/docs now"
    )


def test_link_whose_text_is_the_url_becomes_just_the_url():
    assert to_whatsapp_markup("[https://a.example](https://a.example)") == "https://a.example"


def test_bold_uses_a_single_asterisk():
    assert to_whatsapp_markup("a **big** deal") == "a *big* deal"


def test_bold_across_a_newline_is_bolded_per_line():
    assert to_whatsapp_markup("**first\nsecond**") == "*first*\n*second*"


def test_headings_become_plain_lines():
    assert to_whatsapp_markup("# Title\n\n### Sub\ntext") == "Title\n\nSub\ntext"


def test_urls_are_never_altered_by_the_bold_or_heading_rewrites():
    text = "Go to https://x.example/a**b**c and https://y.example/#frag now"
    assert to_whatsapp_markup(text) == text


def test_a_bold_url_keeps_its_characters():
    assert to_whatsapp_markup("**https://a.example/x**") == "*https://a.example/x*"


def test_short_text_is_one_message():
    assert split_for_whatsapp("hello") == ["hello"]
    assert split_for_whatsapp("   ") == []


def test_splits_at_paragraph_boundaries_when_possible():
    first = "a" * 1000
    second = "b" * 1000
    assert split_for_whatsapp(f"{first}\n\n{second}") == [first, second]


def test_falls_back_to_a_line_break_then_a_space():
    words = " ".join(["word"] * 400)  # 1999 chars, only spaces
    parts = split_for_whatsapp(words)
    assert len(parts) == 2
    assert all(len(p) <= MAX_MESSAGE_CHARS for p in parts)
    assert " ".join(parts) == words  # nothing lost or cut mid-word


def test_a_url_straddling_the_limit_is_kept_whole():
    url = "https://example.com/" + "p" * 80
    text = "x" * (MAX_MESSAGE_CHARS - 40) + " " + url + " tail"
    parts = split_for_whatsapp(text)
    assert len(parts) == 2
    assert url in parts[1]
    assert not any(url[:20] in p and url not in p for p in parts)


def test_a_bold_span_is_not_cut():
    span = "*" + " ".join(["bold"] * 30) + "*"
    text = "x" * (MAX_MESSAGE_CHARS - 50) + " " + span + " tail"
    parts = split_for_whatsapp(text)
    assert len(parts) == 2
    assert span in parts[1]
    assert all(p.count("*") % 2 == 0 for p in parts)


def test_more_than_three_parts_ends_with_an_ellipsis():
    text = " ".join(["word"] * 2000)
    parts = split_for_whatsapp(text)
    assert len(parts) == MAX_MESSAGES
    assert all(len(p) <= MAX_MESSAGE_CHARS for p in parts)
    assert parts[-1].endswith(ELLIPSIS)
    assert not parts[0].endswith(ELLIPSIS)


def test_exactly_three_full_parts_do_not_get_an_ellipsis():
    text = "\n\n".join(["a" * 1500] * 3)
    parts = split_for_whatsapp(text)
    assert len(parts) == 3
    assert not parts[-1].endswith(ELLIPSIS)


def test_a_url_longer_than_a_message_is_hard_cut_and_still_bounded():
    parts = split_for_whatsapp("https://example.com/" + "p" * 5000)
    assert all(len(p) <= MAX_MESSAGE_CHARS for p in parts)


def test_formatting_never_creates_or_changes_a_url():
    original = (
        "## Plans\n\nRead **the [guide](https://example.com/guide)** or "
        "[https://example.com/pricing](https://example.com/pricing).\n" + "filler " * 300
    )
    before = set(URL.findall(original.replace("](", " ").replace(")", " ")))
    after = {u.rstrip("*.,)") for part in format_for_whatsapp(original) for u in URL.findall(part)}
    assert after == {u.rstrip("*.,)") for u in before}


def test_a_reply_holding_the_url_placeholder_does_not_break_the_formatting():
    text = "see https://a.example/x and \x0099\x00 or \x000\x00 **bold**"
    out = format_for_whatsapp(text)
    assert out == ["see https://a.example/x and 99 or 0 *bold*"]
