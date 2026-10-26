# Recipe: db-write

The tool stores something for the team to follow up: an escalation, a lead, a ticket, a request.
One table, one DAO, one repository, one tool. Read `docs/database.md` first.

Placeholders: `<thing>` singular snake_case (`ticket`), `<Thing>` its class name (`Ticket`),
`<things>` the table (`tickets`), `<area>` the tool's folder: one per domain noun (`tickets`), shared
by the tools about it and by `tests/test_<area>_tools.py`.

**Columns come from the spec's args**: one column per arg (`Text` for free text, nullable for
optional args), plus `conversation_id` and a `status` whose values come from the spec (the team's
workflow, e.g. `open`, `in_progress`, `closed`). The snippets below show `email`, `issue` and `name`
as examples only.

## Schema

### `backend/app/db/models.py`

```python
class <Thing>Row(TimestampedMixin, Base):
    """<What it is, who reads it.>"""

    __tablename__ = "<things>"
    __table_args__ = (
        CheckConstraint(
            "status in ('open', 'in_progress', 'closed')", name="<things>_status_check"
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
```

### Migration

`make migration m="add <things>"` generates `backend/alembic/versions/000N_add_<things>.py`,
already numbered (revision `"000N"`, `down_revision` the previous one) and in the style of
`0001_initial_schema.py`. **Read it**: remove the "auto generated" comments, check every column
and constraint, and replace the RLS reminder at the end of `upgrade()` with:

```python
    op.execute("alter table public.<things> enable row level security")
```

`make migrate`, `make migrate-check`, `make migrate-roundtrip`. A new table is backward compatible,
so it can merge while the old code runs.

## Data layer

### `backend/app/db/daos/<thing>_dao.py`

```python
from app.db.daos.base_dao import BaseDAO
from app.db.models import <Thing>Row


class <Thing>DAO(BaseDAO[<Thing>Row]):
    model = <Thing>Row
```

### `backend/app/domain/models.py`

```python
class <Thing>(BaseModel):
    id: UUID
    conversation_id: UUID
    email: str
    issue: str
    name: str | None  # optional columns: `| None`, no default (the row always has the attribute)
    status: str
    created_at: datetime
```

### `backend/app/repositories/<thing>_repository.py`

```python
from uuid import UUID

from app.db.daos.<thing>_dao import <Thing>DAO
from app.domain.models import <Thing>


class <Thing>Repository:
    def __init__(self, <things>: <Thing>DAO) -> None:
        self._<things> = <things>

    def create(
        self, conversation_id: UUID, *, email: str, issue: str, name: str | None = None
    ) -> <Thing>:
        row = self._<things>.insert(
            conversation_id=conversation_id, email=email, issue=issue, name=name
        )
        return <Thing>.model_validate(row, from_attributes=True)
```

Keep the signature `create(conversation_id, *, <one keyword per column>)`: the tool calls it with
keywords, and the evaluator's `RecordingRepository.create(conversation_id, **fields)` stands in for
it.

## Tool: `backend/app/tools/<area>/<tool_name>.py`

```python
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, EmailStr, Field

from app.repositories.<thing>_repository import <Thing>Repository
from app.tools.builder import ToolBuilder


class <ToolName>Args(BaseModel):
    email: EmailStr = Field(description="User's email, asked for explicitly")
    issue: str = Field(description="<what to store>, in the user's words")
    name: str | None = Field(default=None, description="User's name if they gave it")


def build_<tool_name>_tool(<things>: <Thing>Repository) -> BaseTool:
    def run(email: str, issue: str, config: RunnableConfig, name: str | None = None) -> str:
        conversation_id = UUID(config["configurable"]["conversation_id"])
        <things>.create(conversation_id, email=email, issue=issue, name=name)
        return "<CODE>: <what happens next, for the agent to tell the user>."

    return (
        ToolBuilder("<tool_name>")
        .describe(
            "<What it does>. <When to call it>. Only call it after the user gave <the required "
            "details>; ask for what is missing first."
        )
        .args(<ToolName>Args)
        .handler(run)
        .build()
    )
```

`EmailStr` rejects a bad email before the handler runs; inside the graph the error goes back to
the model, which asks again.

## Wiring

- `app/tools/registry.py`: add `<things>: <Thing>Repository` to `ToolDeps` and the tool to
  `build_<agent>_tools`.
- `app/api/deps.py` `get_tool_deps`: add
  `<things>=<Thing>Repository(<Thing>DAO(get_sessions()))` to the `ToolDeps(...)` call (keyword
  arguments: keep the dependencies other tools already pass).
- `app/evals/agent_run.py` `eval_tool_deps`: `<things>=RecordingRepository()`, so evaluations
  never write to Postgres.

## Tests: `backend/tests/test_<area>_tools.py`

```python
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools.<area>.<tool_name> import build_<tool_name>_tool


class Fake<Thing>s:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, conversation_id, **fields):
        self.created.append({"conversation_id": conversation_id, **fields})


ARGS = {"email": "ana@example.com", "issue": "<a realistic request>"}


def _config(conversation_id) -> dict:
    return {"configurable": {"conversation_id": str(conversation_id)}}


def test_stores_the_request_for_the_conversation():
    repo, conversation_id = Fake<Thing>s(), uuid4()
    result = build_<tool_name>_tool(repo).invoke(ARGS, config=_config(conversation_id))
    assert result.startswith("<CODE>")
    assert repo.created == [{"conversation_id": conversation_id, "name": None, **ARGS}]


def test_rejects_a_bad_email():
    repo = Fake<Thing>s()
    with pytest.raises(ValidationError):
        build_<tool_name>_tool(repo).invoke({**ARGS, "email": "nope"}, config=_config(uuid4()))
    assert repo.created == []
```

## Prompt, evals, docs

- Prompt: a bullet in "How you answer" saying when to call it, which details to ask for first
  (never guess them), and what to tell the user afterwards (from the tool's result). Several lines
  are fine. Point other failure paths at it if they should end here (e.g. the knowledge tool's
  `NO_RESULTS`).
- Eval cases (`scenario`: the `plan.md` scenario, or `null`):
  - all the details in the question: `category: "action"` (or `"escalation"`),
    `expected_behavior: "act"`, `expected_tools: ["<tool_name>"]`;
  - a detail missing: `expected_behavior: "clarify"`, `expected_tools: []`,
    `forbidden_tools: ["<tool_name>"]` (the agent must ask before storing anything);
  - its failure code, if it has one besides validation.
- Docs: the table in `docs/database.md` (Schema), in `docs/conventions.md` (Secrets and PII) that
  this table holds personal data, the tool's row in `plan.md`. Never log the args.
