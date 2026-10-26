import re

from app.guardrails.base import ALLOW, GuardrailResult


class MaxLengthGuardrail:
    name = "max_length"

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars

    def check(self, text: str) -> GuardrailResult:
        if len(text) <= self.max_chars:
            return ALLOW
        return GuardrailResult(
            allowed=False,
            reason=f"input over {self.max_chars} chars",
            replacement=(
                "That message is a bit long for me. Could you shorten it to the key question?"
            ),
        )


# Cheap first line of defense; the system prompt and tool design are the real boundary.
_INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)",
    r"(reveal|print|show) (your |the )?(system prompt|instructions)",
    r"you are now (?!talking)",
    r"developer mode",
]


class PromptInjectionGuardrail:
    name = "prompt_injection"

    def __init__(self, patterns: list[str] | None = None) -> None:
        self._regex = re.compile("|".join(patterns or _INJECTION_PATTERNS), re.IGNORECASE)

    def check(self, text: str) -> GuardrailResult:
        if not self._regex.search(text):
            return ALLOW
        return GuardrailResult(
            allowed=False,
            reason="prompt injection pattern",
            replacement="I can only help with questions within my scope.",
        )
