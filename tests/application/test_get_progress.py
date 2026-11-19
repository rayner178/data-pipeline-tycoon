"""Tests for the GetProgress use case."""

from datetime import datetime, timedelta
from uuid import UUID

from application.dto import CompletedChallenge, PlayerProgress
from application.use_cases.get_progress import GetProgress
from domain.entities import Attempt, Challenge, Player
from tests.application.fakes import (
    InMemoryAttemptRepository,
    InMemoryChallengeRepository,
    InMemoryPlayerRepository,
)
from tests.domain.factories import NOW, make_attempt, make_challenge, make_player

ROBLOX_USER = 555
PLAYER = make_player(roblox_user_id=ROBLOX_USER)
DEDUPE = make_challenge(id=UUID(int=10), code="dedupe")
JOIN_FIX = make_challenge(id=UUID(int=20), code="join-fix")


def at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def success(
    challenge: Challenge, minutes: int, ms: int, player: Player = PLAYER
) -> Attempt:
    return make_attempt(
        player_id=player.id,
        challenge_id=challenge.id,
        passed=True,
        execution_ms=ms,
        created_at=at(minutes),
    )


def failure(challenge: Challenge, minutes: int) -> Attempt:
    return make_attempt(
        player_id=PLAYER.id, challenge_id=challenge.id, created_at=at(minutes)
    )


def build(
    players: list[Player],
    attempts: list[Attempt],
    challenges: list[Challenge] | None = None,
) -> tuple[GetProgress, InMemoryPlayerRepository]:
    player_repository = InMemoryPlayerRepository(players)
    use_case = GetProgress(
        players=player_repository,
        challenges=InMemoryChallengeRepository(
            [DEDUPE, JOIN_FIX] if challenges is None else challenges
        ),
        attempts=InMemoryAttemptRepository(attempts),
    )
    return use_case, player_repository


def test_new_player_gets_empty_progress_and_is_not_created() -> None:
    use_case, players = build(players=[], attempts=[])

    progress = use_case.execute(ROBLOX_USER)

    assert progress == PlayerProgress(roblox_user_id=ROBLOX_USER, completed=())
    assert players.players == []


def test_player_without_attempts_gets_empty_progress() -> None:
    use_case, _ = build(players=[PLAYER], attempts=[])

    assert use_case.execute(ROBLOX_USER).completed == ()


def test_failures_then_success_reports_code_time_and_best_ms() -> None:
    attempts = [failure(DEDUPE, 0), failure(DEDUPE, 1), success(DEDUPE, 3, ms=40)]
    use_case, _ = build(players=[PLAYER], attempts=attempts)

    progress = use_case.execute(ROBLOX_USER)

    assert progress.completed == (
        CompletedChallenge(code="dedupe", completed_at=at(3), best_ms=40),
    )


def test_several_challenges_are_reported_in_completion_order() -> None:
    attempts = [success(DEDUPE, 5, ms=30), success(JOIN_FIX, 2, ms=80)]
    use_case, _ = build(players=[PLAYER], attempts=attempts)

    progress = use_case.execute(ROBLOX_USER)

    assert [c.code for c in progress.completed] == ["join-fix", "dedupe"]


def test_other_players_attempts_are_not_included() -> None:
    other = make_player(roblox_user_id=999)
    attempts = [success(DEDUPE, 1, ms=10, player=other)]
    use_case, _ = build(players=[PLAYER, other], attempts=attempts)

    assert use_case.execute(ROBLOX_USER).completed == ()


def test_challenge_missing_from_repository_is_omitted() -> None:
    attempts = [success(DEDUPE, 1, ms=10), success(JOIN_FIX, 2, ms=20)]
    use_case, _ = build(players=[PLAYER], attempts=attempts, challenges=[JOIN_FIX])

    progress = use_case.execute(ROBLOX_USER)

    assert [c.code for c in progress.completed] == ["join-fix"]
