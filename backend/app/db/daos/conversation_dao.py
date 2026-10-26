from app.db.daos.base_dao import BaseDAO
from app.db.models import ConversationRow


class ConversationDAO(BaseDAO[ConversationRow]):
    model = ConversationRow
