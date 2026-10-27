from uuid import UUID

from app.db.daos.base_dao import BaseDAO
from app.db.models import MessageRow


class MessageDAO(BaseDAO[MessageRow]):
    model = MessageRow

    def set_content(self, message_id: UUID, content: str) -> bool:
        """Replace the text of one message; False when it does not exist."""
        with self._sessions.begin() as session:
            row = session.get(MessageRow, message_id)
            if row is None:
                return False
            row.content = content
            return True
