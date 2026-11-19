"""Builders for domain objects with valid defaults, shared by domain tests."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from domain.entities import Attempt, Challenge, Difficulty, Player

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def make_player(**overrides: Any) -> Player:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "roblox_user_id": 123456,
        "created_at": NOW,
    }
    fields.update(overrides)
    return Player(**fields)


def make_challenge(**overrides: Any) -> Challenge:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "code": "dedupe-row-number",
        "module": "postgresql",
        "title": "Eliminar duplicados",
        "description": "Usa ROW_NUMBER() para quedarte con una fila por cliente.",
        "difficulty": Difficulty.EASY,
        "setup_sql": "CREATE TABLE customers (id int, name text);",
        "expected_result": [[1, "Ana"], [2, "Luis"]],
        "max_seconds": 2.0,
    }
    fields.update(overrides)
    return Challenge(**fields)


def make_attempt(**overrides: Any) -> Attempt:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "player_id": uuid4(),
        "challenge_id": uuid4(),
        "submitted_sql": "SELECT 1;",
        "passed": False,
        "execution_ms": 15,
        "error_message": None,
        "created_at": NOW,
    }
    fields.update(overrides)
    return Attempt(**fields)
