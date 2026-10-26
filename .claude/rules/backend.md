---
paths:
  - "backend/app/**/*.py"
  - "backend/tests/**/*.py"
---
# Backend

Before changing backend code, read `docs/architecture/backend.md` (layers, chat turn, tools,
guardrails) and follow `docs/conventions.md`. Tools follow `/new-tool`; every tool and guardrail
needs a unit test with a fake (no real LLM).
