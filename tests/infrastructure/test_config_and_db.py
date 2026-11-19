"""Tests for environment configuration helpers and Windows -> WSL2 DB fallback."""

import sys
from pathlib import Path

import pytest

from infrastructure import db as db_module
from infrastructure.config import get_sandbox_database_url
from infrastructure.db import resolve_database_url


def test_get_sandbox_database_url_returns_none_when_unset_or_blank(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SANDBOX_DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://u:p@localhost/db\n", encoding="utf-8"
    )

    assert get_sandbox_database_url(env_file) is None

    monkeypatch.setenv("SANDBOX_DATABASE_URL", "   ")
    assert get_sandbox_database_url(env_file) is None


def test_get_sandbox_database_url_reads_env_and_normalizes_scheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'SANDBOX_DATABASE_URL="postgres://sb:pw@ep-demo.neon.tech/neondb?sslmode=require"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("SANDBOX_DATABASE_URL", raising=False)

    from_file = get_sandbox_database_url(env_file)
    assert (
        from_file
        == "postgresql+psycopg://sb:pw@ep-demo.neon.tech/neondb?sslmode=require"
    )

    monkeypatch.setenv(
        "SANDBOX_DATABASE_URL",
        "postgresql://sb2:pw2@ep-demo.neon.tech/neondb?sslmode=require",
    )
    from_env = get_sandbox_database_url(env_file)
    assert (
        from_env
        == "postgresql+psycopg://sb2:pw2@ep-demo.neon.tech/neondb?sslmode=require"
    )


def test_resolve_database_url_skips_wsl_fallback_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_database_url.cache_clear()
    url = "postgresql+psycopg://tycoon:secret@localhost:5432/tycoon"
    monkeypatch.setattr(sys, "platform", "linux")

    def _unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("WSL/local probe must not run on Linux")

    monkeypatch.setattr(db_module, "_can_connect_server", _unexpected_call)
    monkeypatch.setattr(db_module, "_detect_wsl_ip", _unexpected_call)

    assert resolve_database_url(url) == url
    resolve_database_url.cache_clear()


def test_resolve_database_url_skips_wsl_fallback_for_remote_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_database_url.cache_clear()
    url = (
        "postgresql+psycopg://neondb_owner:pw@ep-demo.us-east-2.aws.neon.tech:5432/"
        "neondb?sslmode=require"
    )
    monkeypatch.setattr(sys, "platform", "win32")

    def _unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("WSL/local probe must not run for remote Neon hosts")

    monkeypatch.setattr(db_module, "_can_connect_server", _unexpected_call)
    monkeypatch.setattr(db_module, "_detect_wsl_ip", _unexpected_call)

    assert resolve_database_url(url) == url
    resolve_database_url.cache_clear()


def test_resolve_database_url_uses_wsl_ip_only_when_windows_localhost_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_database_url.cache_clear()
    url = "postgresql+psycopg://tycoon:secret@localhost:5432/tycoon?sslmode=disable"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        db_module,
        "_can_connect_server",
        lambda parsed: parsed.host == "172.25.10.5",
    )
    monkeypatch.setattr(db_module, "_detect_wsl_ip", lambda: "172.25.10.5")

    resolved = resolve_database_url(url)
    assert resolved == (
        "postgresql+psycopg://tycoon:secret@172.25.10.5:5432/tycoon?sslmode=disable"
    )
    resolve_database_url.cache_clear()
