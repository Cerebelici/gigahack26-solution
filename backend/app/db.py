import threading
from collections.abc import Iterator
from functools import cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.models import Base

_schema_lock = threading.Lock()
_schema_ready = False


@cache
def get_engine() -> Engine:
    return create_engine(config.database_url(), pool_pre_ping=True)


@cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def init_db(engine: Engine | None = None) -> None:
    """Enable PostGIS and create any missing tables and indexes. Safe to run repeatedly."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)


def ensure_schema() -> None:
    # Done on first use rather than at startup so the tile endpoints work without a database.
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if not _schema_ready:
            init_db()
            _schema_ready = True


def get_db() -> Iterator[Session]:
    ensure_schema()
    with _session_factory()() as session:
        yield session


if __name__ == "__main__":
    init_db()
    print(f"Schema ready at {get_engine().url.render_as_string(hide_password=True)}")
