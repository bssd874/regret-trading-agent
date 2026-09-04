import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.core.config import settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str):
    engine_options = {}
    if database_url.startswith("sqlite"):
        engine_options["connect_args"] = {"check_same_thread": False}
    else:
        # Hosted PostgreSQL drops idle connections, so pooled connections are
        # verified before reuse. Serverless invocations additionally keep no
        # pool at all, because the process may be frozen between requests.
        engine_options["pool_pre_ping"] = True
        if os.getenv("VERCEL"):
            engine_options["poolclass"] = NullPool

    configured_engine = create_engine(database_url, **engine_options)

    if database_url.startswith("sqlite"):
        @event.listens_for(configured_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return configured_engine


engine = build_engine(settings.database_url)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
