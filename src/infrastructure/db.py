"""Database engine helpers with Windows -> WSL2 localhost fallback."""

import functools
import subprocess
import sys

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from infrastructure.config import get_database_url

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


@functools.lru_cache(maxsize=8)
def resolve_database_url(url: str) -> str:
    """Resolve localhost against WSL2 when a local Windows Postgres holds port 5432."""
    parsed = make_url(url)
    if sys.platform != "win32" or parsed.host not in _LOCAL_HOSTS:
        return url
    if _can_connect(url):
        return url
    wsl_ip = _detect_wsl_ip()
    if not wsl_ip:
        return url
    candidate = parsed.set(host=wsl_ip).render_as_string(hide_password=False)
    if _can_connect(candidate):
        return candidate
    return url


def create_db_engine(url: str | None = None) -> Engine:
    """Create a SQLAlchemy Engine from the given URL or DATABASE_URL."""
    resolved = resolve_database_url(url if url is not None else get_database_url())
    return create_engine(resolved, pool_pre_ping=True)


def _can_connect(url: str) -> bool:
    engine = create_engine(url, connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


def _detect_wsl_ip() -> str | None:
    try:
        completed = subprocess.run(
            ["wsl", "hostname", "-I"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    tokens = completed.stdout.strip().split()
    return tokens[0] if tokens else None
