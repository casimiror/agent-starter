"""Turn the agent's Markdown reply into text a voice can read aloud. Pure functions, no I/O.

This runs after the output guardrails (AllowedLinksGuardrail), so it only ever removes: it never
creates or rewrites a URL. A URL can't be read out usefully, so every one is dropped and, once per
reply, `link_phrase` tells the caller where to look instead.
"""

import re

SENTENCE_END = ".!?"

_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
# Does not end on punctuation that follows a URL in prose, nor on Markdown emphasis markers.
_URL = re.compile(r"https?://[^\s<>\]\)]*[^\s<>\]\).,;:!?'\"*_]")
_FENCE = re.compile(r"^[ \t]*(```|~~~).*$")
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+")
_BULLET = re.compile(r"^[ \t]*(?:[-*+•]|\d{1,3}[.)])[ \t]+")
_QUOTE = re.compile(r"^[ \t]*>[ \t]?")
_RULE = re.compile(r"^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$")
_TABLE_SEPARATOR = re.compile(r"^\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)*\|?$")
_BOLD = re.compile(r"\*\*(.*?)\*\*|__(.*?)__")
_ITALIC_STAR = re.compile(r"\*(?!\s)([^*\n]+?)\*")
_ITALIC_UNDERSCORE = re.compile(r"(?<!\w)_(?!\s)([^_\n]+?)_(?!\w)")
_CODE = re.compile(r"`([^`\n]*)`")
_EMPTY_PAIR = re.compile(r"\(\s*\)|\[\s*\]|<\s*>")


def _inline(text: str) -> tuple[str, bool]:
    """Strip inline Markdown from one line. The flag says a URL was removed."""
    removed = False

    def link(match: re.Match[str]) -> str:
        nonlocal removed
        removed = removed or bool(_URL.match(match[2]))
        return match[1]

    text = _IMAGE_OR_LINK.sub(link, text)
    text, count = _URL.subn("", text)
    removed = removed or count > 0
    text = _CODE.sub(r"\1", text)
    text = _BOLD.sub(lambda m: m[1] or m[2], text)
    text = _ITALIC_STAR.sub(r"\1", text)
    text = _ITALIC_UNDERSCORE.sub(r"\1", text)
    text = _EMPTY_PAIR.sub("", text)
    text = text.replace("<", "").replace(">", "")
    text = text.replace("|", ", ").strip(" ,")
    return text, removed


def _sentence(text: str) -> str:
    return text if text.endswith(tuple(SENTENCE_END)) or text.endswith((":", ";")) else text + "."


def format_for_speech(text: str, link_phrase: str) -> str:
    """Markdown -> plain sentences for text-to-speech.

    Links keep their text, bold/italic/code lose their markers, headings and list items become
    sentences, every URL is removed and, when any was, `link_phrase` closes the reply (once)."""
    spoken: list[str] = []
    any_url = False
    in_fence = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        line = raw.strip()
        if not line or _RULE.match(line) or _TABLE_SEPARATOR.match(line):
            continue
        block = False
        if not in_fence:
            for pattern in (_HEADING, _BULLET):
                if pattern.match(line):
                    line, block = pattern.sub("", line, count=1), True
            line = _QUOTE.sub("", line)
        content, removed = _inline(line)
        any_url = any_url or removed
        if content.strip(" .,;:"):
            spoken.append(_sentence(content) if block else content)
    result = re.sub(r"\s+", " ", " ".join(spoken)).strip()
    result = re.sub(r"\s+([.,;:!?])", r"\1", result)
    if any_url and link_phrase.strip():
        result = f"{result} {link_phrase.strip()}".strip()
    return result


def truncate_speech(text: str, limit: int) -> str:
    """At most `limit` characters, ending on a sentence (else a word) boundary. Twilio's <Say>
    rejects text over 4096 characters."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence_end = max(window.rfind(mark) for mark in SENTENCE_END)
    if sentence_end >= limit // 2:
        return window[: sentence_end + 1]
    space = window.rfind(" ")
    return window[:space].rstrip() if space > 0 else window
