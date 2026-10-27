import re

import pytest

from app.services.voice_format import format_for_speech, truncate_speech

PHRASE = "I can't read links aloud; check our website."


def speak(text: str) -> str:
    return format_for_speech(text, PHRASE)


def test_plain_text_is_unchanged():
    assert speak("We open at nine. Come by!") == "We open at nine. Come by!"


def test_bold_italic_and_code_lose_their_markers():
    assert speak("This is **very** _clear_, *really*, and `code`.") == (
        "This is very clear, really, and code."
    )


def test_snake_case_words_keep_their_underscores():
    assert speak("Use the my_tool_name option") == "Use the my_tool_name option"


def test_headings_become_sentences():
    assert speak("## Pricing\nIt depends.") == "Pricing. It depends."


def test_bullets_and_numbered_items_become_sentences():
    text = "Options:\n- Basic plan\n* Pro plan.\n1. First step\n2) Second step"
    assert speak(text) == "Options: Basic plan. Pro plan. First step. Second step."


def test_paragraphs_and_blank_lines_collapse_into_one_line():
    assert speak("One.\n\n\nTwo.\n") == "One. Two."


def test_a_link_keeps_its_text_and_the_phrase_follows():
    assert speak("See [our pricing](https://example.com/pricing) for details.") == (
        f"See our pricing for details. {PHRASE}"
    )


def test_a_bare_url_is_removed_and_the_phrase_added_once():
    text = "Visit https://example.com/a or https://example.com/b."
    spoken = speak(text)
    assert "http" not in spoken and "example.com" not in spoken
    assert spoken.count(PHRASE) == 1
    assert spoken == f"Visit or. {PHRASE}"


def test_an_autolink_and_a_url_in_parentheses_are_removed():
    spoken = speak("Docs <https://example.com/docs> and (https://example.com/x) exist.")
    assert spoken == f"Docs and exist. {PHRASE}"


def test_trailing_punctuation_next_to_a_url_does_not_leave_the_url_behind():
    spoken = speak("Go to https://example.com/page.")
    assert "example" not in spoken and spoken.startswith("Go to")


def test_a_url_in_bold_is_removed_cleanly():
    spoken = speak("**https://example.com/a**")
    assert spoken == PHRASE


def test_the_link_text_that_is_itself_a_url_is_removed():
    assert speak("[https://example.com](https://example.com)") == PHRASE


def test_a_non_http_link_keeps_its_text_without_the_phrase():
    assert speak("Write to [support](mailto:help@example.com).") == "Write to support."


def test_no_url_means_no_phrase():
    assert PHRASE not in speak("Nothing to link here.")


def test_an_empty_phrase_adds_nothing():
    assert format_for_speech("See https://example.com now.", "") == "See now."


def test_code_fences_keep_their_content_without_the_fence():
    assert speak("Run:\n```bash\nmake up\n```\nDone.") == "Run: make up Done."


def test_blockquotes_rules_and_tables_are_flattened():
    text = "> quoted\n---\n| a | b |\n|---|---|\n| 1 | 2 |"
    assert speak(text) == "quoted a, b 1, 2"


def test_images_keep_their_alt_text():
    assert speak("![Our logo](https://example.com/logo.png)") == f"Our logo {PHRASE}"


def test_nothing_is_ever_invented():
    # Every word of the spoken text comes from the reply, apart from the configured phrase.
    reply = "**Plan A** costs less.\n- See [details](https://example.com/a)\n- Call us"
    spoken = speak(reply).replace(PHRASE, "")
    assert set(re.findall(r"[a-z]+", spoken.lower())) <= set(re.findall(r"[a-z]+", reply.lower()))
    assert "http" not in speak(reply)


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "---", "```\n```"])
def test_empty_or_markup_only_input_is_empty(text):
    assert speak(text) == ""


def test_truncate_keeps_short_text():
    assert truncate_speech("Short.", 100) == "Short."


def test_truncate_ends_on_a_sentence():
    text = "First sentence here. Second sentence here. Third sentence here."
    assert truncate_speech(text, 45) == "First sentence here. Second sentence here."


def test_truncate_falls_back_to_a_word_boundary():
    assert truncate_speech("word " * 30, 22) == "word word word word"
