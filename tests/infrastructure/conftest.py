"""Integration test fixtures targeting a dedicated PostgreSQL test database."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.config import derive_test_database_url, get_database_url
from infrastructure.db import create_db_engine, resolve_database_url

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAFE_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _ensure_test_database(test_url: str) -> None:
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


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    raw_test_url = derive_test_database_url(get_database_url())
    resolved_test_url = resolve_database_url(raw_test_url)
    _ensure_test_database(resolved_test_url)

    alembic_cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", resolved_test_url)
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")

    engine = create_db_engine(resolved_test_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(test_engine: Engine) -> Iterator[sessionmaker[Session]]:
    _clean_tables(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        _clean_tables(test_engine)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


def _clean_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM attempts"))
        conn.execute(text("DELETE FROM players"))
        conn.execute(text("DELETE FROM challenges"))
