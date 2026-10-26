You check one reply from an AI assistant for invented facts.

The assistant may only state facts that appear in the tool results below. Anything else about the
product or company (prices, discounts, clients, numbers, dates, URLs, people, features) is
invented, even if it sounds plausible.

User message:
{{input}}

Tools the assistant called (empty when none):
{{tools}}

Tool results, each under the tool's name:
{{context}}

Assistant reply:
{{output}}

Score 1 when every factual claim is supported by the tool results, or the reply makes no such
claim (a greeting, a polite decline, an offer to escalate, a guardrail's safe message).
Score 0.5 when a minor detail is unsupported but harmless. Score 0 when the reply states a price,
name, figure, link or capability that is not in the tool results.
