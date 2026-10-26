"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

import sqlalchemy as sa
${imports if imports else ""}
from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}
    # A new table in `public`? Enable RLS here, in the same revision (docs/database.md):
    # op.execute("alter table public.<table> enable row level security")


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
