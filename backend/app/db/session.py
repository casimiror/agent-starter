from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.url import database_config


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    db = database_config(settings.database_url)
    if settings.serverless:
        # A function instance can be frozen or dropped at any time: hold no idle connections.
        # Pooling is Supavisor's job (transaction pooler, see app/db/url.py).
        engine = create_engine(db.url, poolclass=NullPool, connect_args=db.connect_args)
    else:
        engine = create_engine(
            db.url, pool_pre_ping=True, pool_size=5, connect_args=db.connect_args
        )
    return sessionmaker(engine, expire_on_commit=False)
