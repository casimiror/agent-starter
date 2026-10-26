from app.db.daos.base_dao import BaseDAO
from app.db.models import MessageRow


class MessageDAO(BaseDAO[MessageRow]):
    model = MessageRow
