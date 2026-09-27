import os

# API tests truncate tables, so they never run against the DATABASE_URL in .env.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://localhost:5432/gigahack_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET", "test-secret")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app import db as app_db  # noqa: E402

TABLES = "annotations, rasters, projects, users"


def _create_database_if_missing() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = url.set(database="postgres").set(drivername="postgresql")
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database)))


@pytest.fixture(scope="session")
def engine():
    _create_database_if_missing()
    app_db.init_db()
    return app_db.get_engine()


@pytest.fixture
def db_conn(engine):
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    with engine.connect() as conn:
        yield conn
