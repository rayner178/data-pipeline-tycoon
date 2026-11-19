"""Integration test fixtures targeting a dedicated PostgreSQL test database."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.config import derive_test_database_url, get_database_url
from infrastructure.db import create_db_engine, resolve_database_url
from tests.conftest import ensure_test_database

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    raw_test_url = derive_test_database_url(get_database_url())
    resolved_test_url = resolve_database_url(raw_test_url)
    ensure_test_database(resolved_test_url)

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
