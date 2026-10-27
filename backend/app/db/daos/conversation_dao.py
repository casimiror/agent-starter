from uuid import UUID

from sqlalchemy import select

from app.db.daos.base_dao import BaseDAO
from app.db.models import ConversationRow


class ConversationDAO(BaseDAO[ConversationRow]):
    model = ConversationRow

    def latest_for_visitor(self, visitor_id: UUID, channel: str) -> ConversationRow | None:
        stmt = (
            select(ConversationRow)
            .where(ConversationRow.visitor_id == visitor_id, ConversationRow.channel == channel)
            .order_by(ConversationRow.created_at.desc())
            .limit(1)
        )
        with self._sessions() as session:
            return session.scalars(stmt).first()
