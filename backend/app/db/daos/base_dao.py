from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


class BaseDAO[RowT: Base]:
    """Thin CRUD over one table. Each call is its own short transaction.

    Returns ORM rows; repositories turn them into domain models.
    """

    model: type[RowT]

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def insert(self, **values: Any) -> RowT:
        with self._sessions.begin() as session:
            row = self.model(**values)
            session.add(row)
            session.flush()
            session.refresh(row)
            return row

    def get(self, row_id: Any) -> RowT | None:
        with self._sessions() as session:
            return session.get(self.model, row_id)

    def list_by(
        self,
        column: str,
        value: Any,
        *,
        order_by: str = "created_at",
        desc: bool = False,
        limit: int | None = None,
    ) -> list[RowT]:
        order_col = getattr(self.model, order_by)
        stmt = (
            select(self.model)
            .where(getattr(self.model, column) == value)
            .order_by(order_col.desc() if desc else order_col)
            .limit(limit)
        )
        with self._sessions() as session:
            return list(session.scalars(stmt))
