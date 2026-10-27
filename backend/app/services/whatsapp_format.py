"""Turn the agent's Markdown reply into WhatsApp messages. Pure functions, no I/O.

This runs after the output guardrails (AllowedLinksGuardrail), so it must never create, drop or
alter a URL: links are rewritten to `text: url`, URLs are shielded from the other rewrites, and
the splitter never cuts through one.
"""

import re

# WhatsApp (Twilio) rejects bodies over 1600 characters.
MAX_MESSAGE_CHARS = 1600
MAX_MESSAGES = 3
ELLIPSIS = "…"

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
# The splitter's notion of a URL. `*` is allowed here so a URL followed by a closing bold marker
# is kept whole, never cut.
_URL = re.compile(r"https?://\S+")
# The formatter's: does not end on `*`, so the closing marker of `**https://a.example**` is left
# out of the URL and the bold still converts.
_URL_BARE = re.compile(r"https?://\S*[^\s*]")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_BOLD_SPAN = re.compile(r"\*[^*\n]+\*")
_SHIELD = "\x00{}\x00"
_SHIELDED = re.compile(r"\x00(\d+)\x00")


def _bold_per_line(match: re.Match[str]) -> str:
    """`**a\\nb**` -> `*a*\\n*b*`: WhatsApp does not bold across a line break."""
    lines = match[1].split("\n")
    return "\n".join(f"*{line.strip()}*" if line.strip() else line for line in lines)


def to_whatsapp_markup(text: str) -> str:
    """`[text](url)` -> `text: url` (just `url` when they are the same), `**bold**` -> `*bold*`,
    headings -> plain lines."""
    text = _LINK.sub(lambda m: m[2] if m[1] == m[2] else f"{m[1]}: {m[2]}", text)

    urls: list[str] = []

    def shield(match: re.Match[str]) -> str:
        urls.append(match[0])
        return _SHIELD.format(len(urls) - 1)

    # Bold and heading rewrites must not touch a URL, whatever characters it holds.
    text = _URL_BARE.sub(shield, text)
    text = _BOLD.sub(_bold_per_line, text)
    text = _HEADING.sub("", text)
    return _SHIELDED.sub(lambda m: urls[int(m[1])], text)


def _protected(text: str) -> list[tuple[int, int]]:
    """Spans a message must not be cut inside: URLs and `*bold*`."""
    return [m.span() for pattern in (_URL, _BOLD_SPAN) for m in pattern.finditer(text)]


def _cut_point(text: str, limit: int) -> int:
    """Where to end the first message of `text` (longer than `limit`): at a paragraph break, else
    a line break, else a space, and never inside a URL or a bold span."""
    spans = _protected(text)

    def inside(index: int) -> bool:
        return any(start < index < end for start, end in spans)

    for min_cut in (limit // 2, 1):  # prefer a roomy first message, but any boundary beats none
        for separator in ("\n\n", "\n", " "):
            index = text.rfind(separator, min_cut, limit + 1)
            while index >= min_cut and inside(index):
                index = text.rfind(separator, min_cut, index)
            if index >= min_cut:
                return index
    # No boundary: end just before the protected span the limit falls in, if there is room.
    for start, end in spans:
        if start < limit < end and start > 0:
            return start
    return limit  # a single URL longer than a whole message: nothing better exists


def split_for_whatsapp(text: str) -> list[str]:
    """Split into messages of at most `MAX_MESSAGE_CHARS`, at most `MAX_MESSAGES`. When text is
    left over, the last message ends with an ellipsis."""
    text = text.strip()
    parts: list[str] = []
    while len(parts) < MAX_MESSAGES:
        if len(text) <= MAX_MESSAGE_CHARS:
            return [*parts, text] if text else parts
        last = len(parts) == MAX_MESSAGES - 1
        limit = MAX_MESSAGE_CHARS - (len(ELLIPSIS) if last else 0)
        cut = _cut_point(text, limit)
        head = text[:cut].rstrip()
        if last:
            return [*parts, head + ELLIPSIS]
        parts.append(head)
        text = text[cut:].lstrip()
    return parts


def format_for_whatsapp(text: str) -> list[str]:
    return split_for_whatsapp(to_whatsapp_markup(text))
