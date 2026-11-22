"""Database engine, sessions and schema setup.

Run `python -m app.db` once to create the tables (needed for Neon or any DB
that did not start from our Docker Compose file).
"""

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

INIT_SQL = Path(__file__).parent / "sql" / "init.sql"


@lru_cache
def get_engine() -> Engine:
    # connect_timeout: fail fast with an error instead of hanging when the DB is not running
    return create_engine(
        get_settings().database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = sessionmaker(bind=get_engine())()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Run init.sql (CREATE ... IF NOT EXISTS, so it is idempotent)."""
    sql = INIT_SQL.read_text(encoding="utf-8")
    with get_engine().begin() as conn:
        conn.exec_driver_sql(sql)


def ping_db() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


if __name__ == "__main__":
    init_db()
    print("Database schema is ready.")
