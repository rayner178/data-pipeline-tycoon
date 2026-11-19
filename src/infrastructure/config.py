"""Environment configuration helpers for infrastructure."""

import os
from pathlib import Path

from sqlalchemy.engine import make_url

_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def get_database_url(env_file: Path | None = None) -> str:
    """Read DATABASE_URL from environment (or .env) and normalize the psycopg driver."""
    raw = os.environ.get("DATABASE_URL")
    if not raw or not raw.strip():
        raw = _read_dotenv_var("DATABASE_URL", env_file or _DEFAULT_ENV_PATH)
    if not raw or not raw.strip():
        raise RuntimeError("DATABASE_URL environment variable is required")
    return _normalize_psycopg_scheme(raw.strip())


def derive_test_database_url(
    database_url: str, *, explicit_test_url: str | None = None
) -> str:
    """Return a separate database URL for integration tests."""
    candidate = (
        explicit_test_url
        if explicit_test_url is not None
        else os.environ.get("TEST_DATABASE_URL")
    )
    dev_url = make_url(_normalize_psycopg_scheme(database_url))
    if candidate and candidate.strip():
        test_url = make_url(_normalize_psycopg_scheme(candidate.strip()))
    else:
        if not dev_url.database:
            raise RuntimeError("DATABASE_URL must specify a database name")
        test_db = (
            dev_url.database
            if dev_url.database.endswith("_test")
            else f"{dev_url.database}_test"
        )
        test_url = dev_url.set(database=test_db)
    if test_url.database == dev_url.database:
        raise RuntimeError(
            "Integration test database must be separate from development database"
        )
    return test_url.render_as_string(hide_password=False)


def _normalize_psycopg_scheme(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _read_dotenv_var(name: str, path: Path) -> str | None:
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None
