"""Tests for domain entity invariants."""

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal

import pytest

from domain.entities import Difficulty
from domain.errors import DomainValidationError
from tests.domain.factories import make_attempt, make_challenge, make_player

NAIVE = datetime(2026, 11, 17, 12, 0)

# --- Player -----------------------------------------------------------------


def test_valid_player_is_created() -> None:
    player = make_player(roblox_user_id=42)

    assert player.roblox_user_id == 42


@pytest.mark.parametrize("roblox_user_id", [0, -1])
def test_player_requires_positive_roblox_user_id(roblox_user_id: int) -> None:
    with pytest.raises(DomainValidationError):
        make_player(roblox_user_id=roblox_user_id)


def test_player_requires_timezone_aware_created_at() -> None:
    with pytest.raises(DomainValidationError):
        make_player(created_at=NAIVE)


def test_player_is_immutable() -> None:
    player = make_player()

    with pytest.raises(FrozenInstanceError):
        player.roblox_user_id = 7  # type: ignore[misc]


# --- Challenge --------------------------------------------------------------


def test_challenge_is_unordered_by_default() -> None:
    assert make_challenge().ordered is False


def test_challenge_freezes_expected_result_into_tuple_of_tuples() -> None:
    challenge = make_challenge(expected_result=[[1, "Ana"], [2, "Luis"]])

    assert challenge.expected_result == ((1, "Ana"), (2, "Luis"))
    assert isinstance(challenge.expected_result, tuple)
    assert all(isinstance(row, tuple) for row in challenge.expected_result)


def test_challenge_is_not_affected_by_later_changes_to_the_source_list() -> None:
    source: list[list[int | str]] = [[1, "Ana"]]
    challenge = make_challenge(expected_result=source)

    source[0][1] = "Changed"
    source.append([2, "Luis"])

    assert challenge.expected_result == ((1, "Ana"),)


def test_challenge_accepts_empty_expected_result() -> None:
    assert make_challenge(expected_result=[]).expected_result == ()


@pytest.mark.parametrize("field", ["code", "module", "title", "setup_sql"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_challenge_requires_non_blank_text(field: str, blank: str) -> None:
    with pytest.raises(DomainValidationError):
        make_challenge(**{field: blank})


@pytest.mark.parametrize("max_seconds", [0, -1.5])
def test_challenge_requires_positive_max_seconds(max_seconds: float) -> None:
    with pytest.raises(DomainValidationError):
        make_challenge(max_seconds=max_seconds)


def test_challenge_rejects_rows_with_different_column_counts() -> None:
    with pytest.raises(DomainValidationError):
        make_challenge(expected_result=[[1, "Ana"], [2]])


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), Decimal("NaN"), Decimal("-Infinity")]
)
def test_challenge_rejects_non_finite_expected_values(value: float | Decimal) -> None:
    with pytest.raises(DomainValidationError):
        make_challenge(expected_result=[[value]])


def test_challenge_rejects_unsupported_cell_types() -> None:
    with pytest.raises(DomainValidationError):
        make_challenge(expected_result=[[NAIVE]])


def test_challenge_is_solved_by_matching_result_in_any_order() -> None:
    challenge = make_challenge(expected_result=[[1, "Ana"], [2, "Luis"]])

    assert challenge.is_solved_by([(2, "Luis"), (1, "Ana")])


def test_challenge_is_not_solved_by_different_result() -> None:
    challenge = make_challenge(expected_result=[[1, "Ana"], [2, "Luis"]])

    assert not challenge.is_solved_by([(1, "Ana"), (1, "Ana"), (2, "Luis")])


def test_ordered_challenge_requires_same_row_order() -> None:
    challenge = make_challenge(expected_result=[[1], [2]], ordered=True)

    assert challenge.is_solved_by([(1,), (2,)])
    assert not challenge.is_solved_by([(2,), (1,)])


def test_difficulty_levels_are_ordered() -> None:
    assert Difficulty.EASY < Difficulty.MEDIUM < Difficulty.HARD


# --- Attempt ----------------------------------------------------------------


def test_failed_attempt_may_have_error_message_and_no_execution_time() -> None:
    attempt = make_attempt(passed=False, execution_ms=None, error_message="syntax")

    assert attempt.passed is False


def test_passed_attempt_is_created() -> None:
    attempt = make_attempt(passed=True, execution_ms=30, error_message=None)

    assert attempt.passed is True


def test_passed_attempt_cannot_have_error_message() -> None:
    with pytest.raises(DomainValidationError):
        make_attempt(passed=True, execution_ms=30, error_message="boom")


def test_passed_attempt_requires_execution_time() -> None:
    with pytest.raises(DomainValidationError):
        make_attempt(passed=True, execution_ms=None)


def test_attempt_rejects_negative_execution_time() -> None:
    with pytest.raises(DomainValidationError):
        make_attempt(execution_ms=-1)


@pytest.mark.parametrize("blank", ["", "   "])
def test_attempt_requires_non_blank_sql(blank: str) -> None:
    with pytest.raises(DomainValidationError):
        make_attempt(submitted_sql=blank)


def test_attempt_requires_timezone_aware_created_at() -> None:
    with pytest.raises(DomainValidationError):
        make_attempt(created_at=NAIVE)
