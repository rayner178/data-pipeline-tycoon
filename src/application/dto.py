"""Data returned by the use cases (framework-free)."""

from dataclasses import dataclass
from datetime import datetime

from domain.entities import Difficulty


@dataclass(frozen=True, slots=True)
class ChallengeSummary:
    """Public view of a challenge: never includes setup_sql or expected_result."""

    code: str
    module: str
    title: str
    description: str
    difficulty: Difficulty


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    passed: bool
    execution_ms: int | None
    message: str
    columns: tuple[str, ...] = ()
    preview_rows: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class CompletedChallenge:
    code: str
    completed_at: datetime
    best_ms: int


@dataclass(frozen=True, slots=True)
class PlayerProgress:
    roblox_user_id: int
    completed: tuple[CompletedChallenge, ...]
