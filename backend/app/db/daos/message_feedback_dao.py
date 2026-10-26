from uuid import UUID

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert

from app.db.daos.base_dao import BaseDAO
from app.db.models import MessageFeedbackRow


class MessageFeedbackDAO(BaseDAO[MessageFeedbackRow]):
    model = MessageFeedbackRow

    def upsert(self, message_id: UUID, rating: str) -> MessageFeedbackRow:
        """One statement, so two quick clicks can't create two rows for the same message."""
        stmt = (
            insert(MessageFeedbackRow)
            .values(message_id=message_id, rating=rating)
            .on_conflict_do_update(
                index_elements=[MessageFeedbackRow.message_id],
                set_={"rating": rating, "updated_at": func.now()},
            )
            .returning(MessageFeedbackRow)
        )
        with self._sessions.begin() as session:
            return session.scalars(stmt).one()

    def delete_by_message(self, message_id: UUID) -> bool:
        stmt = delete(MessageFeedbackRow).where(MessageFeedbackRow.message_id == message_id)
        with self._sessions.begin() as session:
            return session.execute(stmt).rowcount > 0
