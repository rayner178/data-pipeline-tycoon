"""Tests for progress computation from a player's attempts."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from domain.errors import DomainValidationError
from domain.progress import Progress, compute_progress
from tests.domain.factories import NOW, make_attempt

PLAYER = uuid4()
CHALLENGE_A = UUID(int=1)
CHALLENGE_B = UUID(int=2)


def at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def test_no_attempts_gives_empty_progress() -> None:
    assert compute_progress(PLAYER, []) == []


def test_only_failed_attempts_give_empty_progress() -> None:
    attempts = [
        make_attempt(player_id=PLAYER, challenge_id=CHALLENGE_A, created_at=at(m))
        for m in range(3)
    ]

    assert compute_progress(PLAYER, attempts) == []


def test_several_failures_before_success() -> None:
    failures = [
        make_attempt(player_id=PLAYER, challenge_id=CHALLENGE_A, created_at=at(m))
        for m in range(3)
    ]
    success = make_attempt(
        player_id=PLAYER,
        challenge_id=CHALLENGE_A,
        passed=True,
        execution_ms=40,
        created_at=at(3),
    )

    progress = compute_progress(PLAYER, [*failures, success])

    assert progress == [Progress(PLAYER, CHALLENGE_A, at(3), 40)]


def test_completed_at_is_first_success_and_best_ms_is_fastest_success() -> None:
    attempts = [
        make_attempt(
            player_id=PLAYER,
            challenge_id=CHALLENGE_A,
            passed=True,
            execution_ms=ms,
            created_at=at(minute),
        )
        for minute, ms in [(5, 80), (2, 120), (9, 30)]
    ]

    progress = compute_progress(PLAYER, attempts)

    assert progress == [Progress(PLAYER, CHALLENGE_A, at(2), 30)]


def test_failed_attempts_do_not_count_for_best_time() -> None:
    fast_failure = make_attempt(
        player_id=PLAYER, challenge_id=CHALLENGE_A, execution_ms=1, created_at=at(0)
    )
    success = make_attempt(
        player_id=PLAYER,
        challenge_id=CHALLENGE_A,
        passed=True,
        execution_ms=50,
        created_at=at(1),
    )

    progress = compute_progress(PLAYER, [fast_failure, success])

    assert progress[0].best_ms == 50


def test_only_completed_challenges_appear() -> None:
    failure_a = make_attempt(player_id=PLAYER, challenge_id=CHALLENGE_A)
    success_b = make_attempt(
        player_id=PLAYER, challenge_id=CHALLENGE_B, passed=True, execution_ms=10
    )

    progress = compute_progress(PLAYER, [failure_a, success_b])

    assert [item.challenge_id for item in progress] == [CHALLENGE_B]


def test_progress_is_sorted_by_completed_at() -> None:
    late_a = make_attempt(
        player_id=PLAYER,
        challenge_id=CHALLENGE_A,
        passed=True,
        execution_ms=10,
        created_at=at(4),
    )
    early_b = make_attempt(
        player_id=PLAYER,
        challenge_id=CHALLENGE_B,
        passed=True,
        execution_ms=10,
        created_at=at(1),
    )

    progress = compute_progress(PLAYER, [late_a, early_b])

    assert [item.challenge_id for item in progress] == [CHALLENGE_B, CHALLENGE_A]


def test_ties_on_completed_at_are_broken_by_challenge_id() -> None:
    attempts = [
        make_attempt(
            player_id=PLAYER,
            challenge_id=challenge_id,
            passed=True,
            execution_ms=10,
            created_at=at(3),
        )
        for challenge_id in (CHALLENGE_B, CHALLENGE_A)
    ]

    progress = compute_progress(PLAYER, attempts)

    assert [item.challenge_id for item in progress] == [CHALLENGE_A, CHALLENGE_B]


def test_attempts_from_another_player_are_rejected() -> None:
    foreign = make_attempt(player_id=uuid4(), challenge_id=CHALLENGE_A)

    with pytest.raises(DomainValidationError):
        compute_progress(PLAYER, [foreign])
