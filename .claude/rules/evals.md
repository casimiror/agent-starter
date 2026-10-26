---
paths:
  - "backend/app/evals/**"
---
# Evaluation

Before changing the evaluator or its dataset, read `docs/evaluation.md`. Cover every `plan.md`
scenario, copy keywords from the documents in `expected_sources`, and never let the evaluator
write to a real database (tools get in-memory repositories in `eval_tool_deps`).
