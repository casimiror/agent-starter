from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reason: str | None = None
    # Text shown to the user instead of the blocked input/output.
    replacement: str | None = None


ALLOW = GuardrailResult(allowed=True)


class Guardrail(Protocol):
    name: str

    def check(self, text: str) -> GuardrailResult: ...


def run_guardrails(guardrails: list[Guardrail], text: str) -> GuardrailResult:
    for guardrail in guardrails:
        result = guardrail.check(text)
        if not result.allowed:
            return result
    return ALLOW
