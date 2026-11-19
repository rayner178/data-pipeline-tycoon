"""Shared test helpers across test suites."""

import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_SAFE_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def ensure_test_database(test_url: str) -> None:
    """Create the dedicated PostgreSQL test database idempotently if missing."""
    parsed = make_url(test_url)
    db_name = parsed.database
    if not db_name or not _SAFE_DB_NAME.match(db_name):
        raise RuntimeError(f"Unsafe test database name: {db_name!r}")
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                quoted = admin_engine.dialect.identifier_preparer.quote_identifier(
                    db_name
                )
                conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        admin_engine.dispose()
