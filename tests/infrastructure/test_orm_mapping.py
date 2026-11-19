"""Tests for ORM schema definitions, explicit domain mapping and config."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import BigInteger, Boolean, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from domain.entities import Attempt, Challenge, Difficulty, Player
from infrastructure.config import derive_test_database_url, get_database_url
from infrastructure.orm import (
    AttemptModel,
    Base,
    ChallengeModel,
    PlayerModel,
    attempt_from_domain,
    attempt_to_domain,
    challenge_from_domain,
    challenge_to_domain,
    player_from_domain,
    player_to_domain,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


# --- Config -----------------------------------------------------------------


def test_get_database_url_reads_environment_and_normalizes_scheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/tycoon")

    url = get_database_url(env_file=tmp_path / ".env")

    assert url == "postgresql+psycopg://user:pass@localhost:5432/tycoon"


def test_get_database_url_normalizes_postgresql_scheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/tycoon")

    assert (
        get_database_url(env_file=tmp_path / ".env")
        == "postgresql+psycopg://user:pass@localhost:5432/tycoon"
    )


def test_get_database_url_falls_back_to_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nDATABASE_URL=postgresql+psycopg://u:p@localhost:5432/db\n",
        encoding="utf-8",
    )

    assert (
        get_database_url(env_file=env_file)
        == "postgresql+psycopg://u:p@localhost:5432/db"
    )


def test_get_database_url_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_database_url(env_file=tmp_path / ".env")


def test_derive_test_database_url_appends_suffix() -> None:
    dev_url = "postgresql+psycopg://u:p@localhost:5432/tycoon"

    test_url = derive_test_database_url(dev_url, explicit_test_url=None)

    assert test_url == "postgresql+psycopg://u:p@localhost:5432/tycoon_test"


def test_derive_test_database_url_rejects_same_database() -> None:
    dev_url = "postgresql+psycopg://u:p@localhost:5432/tycoon"

    with pytest.raises(RuntimeError, match="separate"):
        derive_test_database_url(dev_url, explicit_test_url=dev_url)


# --- ORM schema inspection --------------------------------------------------


def test_tables_exist_in_metadata() -> None:
    assert {"players", "challenges", "attempts"}.issubset(Base.metadata.tables)


def test_players_schema_has_timestamptz_bigint_and_unique_constraint() -> None:
    table = Base.metadata.tables["players"]
    assert isinstance(table.c.roblox_user_id.type, BigInteger)
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True
    uniques = {
        tuple(c.columns.keys())
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert ("roblox_user_id",) in uniques


def test_challenges_schema_has_jsonb_ordered_unique_and_index() -> None:
    table = Base.metadata.tables["challenges"]
    assert isinstance(table.c.expected_result.type, JSONB)
    assert isinstance(table.c.ordered.type, Boolean)
    assert table.c.ordered.nullable is False
    uniques = {
        tuple(c.columns.keys())
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert ("code",) in uniques
    index_cols = {tuple(ix.columns.keys()) for ix in table.indexes}
    assert ("difficulty", "code") in index_cols


def test_attempts_schema_has_timestamptz_fks_and_indexes() -> None:
    table = Base.metadata.tables["attempts"]
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True
    assert table.c.execution_ms.nullable is True
    assert table.c.error_message.nullable is True
    fk_targets = {fk.target_fullname for fk in table.foreign_keys}
    assert fk_targets == {"players.id", "challenges.id"}
    index_cols = {tuple(ix.columns.keys()) for ix in table.indexes}
    assert ("player_id",) in index_cols
    assert ("challenge_id",) in index_cols


# --- Explicit domain <-> ORM mapping ----------------------------------------


def test_player_round_trip_mapping() -> None:
    player = Player(id=UUID(int=1), roblox_user_id=9876543210, created_at=NOW)

    model = player_from_domain(player)
    assert isinstance(model, PlayerModel)
    restored = player_to_domain(model)

    assert restored == player


def test_challenge_round_trip_mapping_preserves_decimals_bools_none_and_ordered() -> (
    None
):
    challenge = Challenge(
        id=UUID(int=2),
        code="dedupe-row-number",
        module="postgresql",
        title="Eliminar duplicados",
        description="Usa ROW_NUMBER()",
        difficulty=Difficulty.MEDIUM,
        setup_sql="CREATE TABLE t (id int);",
        expected_result=((1, Decimal("12.5000"), True, None),),
        max_seconds=2.5,
        ordered=True,
    )

    model = challenge_from_domain(challenge)
    assert isinstance(model, ChallengeModel)
    restored = challenge_to_domain(model)

    assert restored == challenge
    assert restored.ordered is True
    assert restored.difficulty is Difficulty.MEDIUM
    assert type(restored.expected_result[0][1]) is Decimal
    assert type(restored.expected_result[0][2]) is bool


def test_attempt_round_trip_mapping_passed_and_failed() -> None:
    passed = Attempt(
        id=UUID(int=3),
        player_id=UUID(int=1),
        challenge_id=UUID(int=2),
        submitted_sql="SELECT 1;",
        passed=True,
        execution_ms=14,
        error_message=None,
        created_at=NOW,
    )
    failed = Attempt(
        id=UUID(int=4),
        player_id=UUID(int=1),
        challenge_id=UUID(int=2),
        submitted_sql="SELEC 1;",
        passed=False,
        execution_ms=None,
        error_message="syntax error",
        created_at=NOW,
    )

    for attempt in (passed, failed):
        model = attempt_from_domain(attempt)
        assert isinstance(model, AttemptModel)
        assert attempt_to_domain(model) == attempt
