"""Domain entities: Player, Challenge and Attempt (SPEC section 5)."""

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from uuid import UUID

from domain.errors import DomainValidationError
from domain.execution_plan import setup_creates_index
from domain.result_matching import QueryResult, freeze_expected_result, results_match


class Difficulty(IntEnum):
    EASY = 1
    MEDIUM = 2
    HARD = 3


@dataclass(frozen=True, slots=True)
class Player:
    id: UUID
    roblox_user_id: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.roblox_user_id <= 0:
            raise DomainValidationError("roblox_user_id must be positive")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class Challenge:
    """A challenge; ``expected_result`` is stored as a tuple of tuples."""

    id: UUID
    code: str
    module: str
    title: str
    description: str
    difficulty: Difficulty
    setup_sql: str
    expected_result: QueryResult
    max_seconds: float
    ordered: bool = False

    def __post_init__(self) -> None:
        _require_text(self.code, "code")
        _require_text(self.module, "module")
        _require_text(self.title, "title")
        _require_text(self.setup_sql, "setup_sql")
        if self.max_seconds <= 0:
            raise DomainValidationError("max_seconds must be positive")
        frozen = freeze_expected_result(self.expected_result)
        object.__setattr__(self, "expected_result", frozen)

    def is_solved_by(self, actual: QueryResult) -> bool:
        """A challenge is solved when the player's result matches the expected one."""
        return results_match(actual, self.expected_result, ordered=self.ordered)

    def requires_index_plan(self) -> bool:
        """Return True when the challenge expects the query plan to use an index."""
        return setup_creates_index(self.setup_sql)


@dataclass(frozen=True, slots=True)
class Attempt:
    id: UUID
    player_id: UUID
    challenge_id: UUID
    submitted_sql: str
    passed: bool
    execution_ms: int | None
    error_message: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.submitted_sql, "submitted_sql")
        _require_aware(self.created_at, "created_at")
        if self.execution_ms is not None and self.execution_ms < 0:
            raise DomainValidationError("execution_ms cannot be negative")
        if self.passed:
            self._validate_passed()

    def _validate_passed(self) -> None:
        if self.execution_ms is None:
            raise DomainValidationError("a passed attempt requires execution_ms")
        if self.error_message is not None:
            raise DomainValidationError("a passed attempt cannot have an error")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise DomainValidationError(f"{field_name} cannot be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must be timezone-aware")
