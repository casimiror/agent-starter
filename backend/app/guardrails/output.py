import re

from app.guardrails.base import ALLOW, GuardrailResult

SAFE_FALLBACK = (
    "I don't want to give you a wrong answer on that. Could you rephrase, or ask me something "
    "else I can help with?"
)


class NoInventedPricesGuardrail:
    """Pricing is quoted by the team, never by the bot."""

    name = "no_invented_prices"
    _money = re.compile(r"(\$|USD|€)\s?\d", re.IGNORECASE)

    def check(self, text: str) -> GuardrailResult:
        if not self._money.search(text):
            return ALLOW
        return GuardrailResult(allowed=False, reason="price in output", replacement=SAFE_FALLBACK)


class AllowedLinksGuardrail:
    """Only URLs from config / knowledge base may appear in answers."""

    name = "allowed_links"
    _url = re.compile(r"https?://[^\s)\]>]+")

    def __init__(self, allowed_prefixes: list[str]) -> None:
        self.allowed_prefixes = [p for p in allowed_prefixes if p]

    def check(self, text: str) -> GuardrailResult:
        for url in self._url.findall(text):
            if not any(url.startswith(p) for p in self.allowed_prefixes):
                return GuardrailResult(
                    allowed=False, reason=f"unknown url {url}", replacement=SAFE_FALLBACK
                )
        return ALLOW
