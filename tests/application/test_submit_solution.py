"""Tests for the SubmitSolution use case."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from application.dto import SubmissionResult
from application.errors import (
    ChallengeNotFound,
    EmptySubmission,
    EvaluatorError,
    EvaluatorUnavailable,
)
from application.evaluation import ExecutionFailed, ExecutionSucceeded
from application.ports import UnitOfWork
from application.use_cases.submit_solution import (
    MESSAGE_INCOMPARABLE,
    MESSAGE_MISMATCH,
    MESSAGE_SOLVED,
    SubmitSolution,
)
from domain.entities import Challenge, Player
from tests.application.fakes import (
    FakeEvaluator,
    FakeUnitOfWork,
    FixedClock,
    InMemoryAttemptRepository,
    InMemoryChallengeRepository,
    InMemoryPlayerRepository,
    SequentialIdGenerator,
)
from tests.domain.factories import NOW, make_challenge, make_player

ROBLOX_USER = 987654
SQL = "SELECT id, name FROM customers;"
CHALLENGE = make_challenge(code="dedupe", expected_result=[[1, "Ana"], [2, "Luis"]])
CORRECT = ExecutionSucceeded(rows=((2, "Luis"), (1, "Ana")), execution_ms=25)


@dataclass
class Env:
    evaluator: FakeEvaluator
    players: InMemoryPlayerRepository
    challenges: InMemoryChallengeRepository = field(
        default_factory=lambda: InMemoryChallengeRepository([CHALLENGE])
    )
    attempts: InMemoryAttemptRepository = field(
        default_factory=InMemoryAttemptRepository
    )
    ids: SequentialIdGenerator = field(default_factory=SequentialIdGenerator)
    uow: UnitOfWork | None = None

    @property
    def use_case(self) -> SubmitSolution:
        return SubmitSolution(
            players=self.players,
            challenges=self.challenges,
            attempts=self.attempts,
            evaluator=self.evaluator,
            clock=FixedClock(NOW),
            ids=self.ids,
            uow=self.uow,
        )

    def submit(self, sql: str = SQL, code: str = "dedupe") -> SubmissionResult:
        return self.use_case.execute(roblox_user_id=ROBLOX_USER, code=code, sql=sql)

    def assert_nothing_saved(self) -> None:
        assert self.attempts.attempts == []
        assert self.players.players == []


def make_env(
    evaluator: FakeEvaluator,
    players: list[Player] | None = None,
    challenges: list[Challenge] | None = None,
) -> Env:
    env = Env(evaluator=evaluator, players=InMemoryPlayerRepository(players or []))
    if challenges is not None:
        env.challenges = InMemoryChallengeRepository(challenges)
    return env


# --- Outcomes ---------------------------------------------------------------


def test_correct_solution_passes_and_is_saved() -> None:
    env = make_env(FakeEvaluator(CORRECT))

    result = env.submit()

    assert result == SubmissionResult(
        passed=True, execution_ms=25, message=MESSAGE_SOLVED
    )
    [attempt] = env.attempts.attempts
    assert attempt.passed is True
    assert attempt.execution_ms == 25
    assert attempt.error_message is None
    assert attempt.submitted_sql == SQL
    assert attempt.challenge_id == CHALLENGE.id


def test_wrong_result_fails_and_is_saved() -> None:
    wrong = ExecutionSucceeded(
        rows=((1, "Ana"), (1, "Ana"), (2, "Luis")), execution_ms=9
    )
    env = make_env(FakeEvaluator(wrong))

    result = env.submit()

    assert result == SubmissionResult(
        passed=False, execution_ms=9, message=MESSAGE_MISMATCH
    )
    [attempt] = env.attempts.attempts
    assert attempt.passed is False
    assert attempt.execution_ms == 9
    assert attempt.error_message is None


@pytest.mark.parametrize("execution_ms", [None, 7])
def test_player_sql_error_fails_and_is_saved(execution_ms: int | None) -> None:
    failed = ExecutionFailed(
        error_message="syntax error at or near SELEC", execution_ms=execution_ms
    )
    env = make_env(FakeEvaluator(failed))

    result = env.submit()

    assert result == SubmissionResult(
        passed=False,
        execution_ms=execution_ms,
        message="syntax error at or near SELEC",
    )
    [attempt] = env.attempts.attempts
    assert attempt.passed is False
    assert attempt.error_message == "syntax error at or near SELEC"


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), Decimal("NaN"), Decimal("-Infinity")]
)
def test_rows_with_non_finite_values_fail_and_are_saved(
    value: float | Decimal,
) -> None:
    env = make_env(FakeEvaluator(ExecutionSucceeded(rows=((value,),), execution_ms=3)))

    result = env.submit()

    assert result == SubmissionResult(
        passed=False, execution_ms=3, message=MESSAGE_MISMATCH
    )
    assert len(env.attempts.attempts) == 1


def test_incomparable_rows_are_a_player_failure_not_an_outage() -> None:
    rows: Any = ((datetime(2026, 1, 1, tzinfo=UTC), "Ana"),)
    env = make_env(FakeEvaluator(ExecutionSucceeded(rows=rows, execution_ms=4)))

    result = env.submit()

    assert result == SubmissionResult(
        passed=False, execution_ms=4, message=MESSAGE_INCOMPARABLE
    )
    [attempt] = env.attempts.attempts
    assert attempt.passed is False
    assert attempt.error_message == MESSAGE_INCOMPARABLE


def test_ordered_challenge_fails_when_row_order_differs() -> None:
    ordered = make_challenge(code="dedupe", expected_result=[[1], [2]], ordered=True)
    reversed_rows = ExecutionSucceeded(rows=((2,), (1,)), execution_ms=5)
    env = make_env(FakeEvaluator(reversed_rows), challenges=[ordered])

    assert env.submit().passed is False


def test_evaluator_receives_challenge_and_sql() -> None:
    evaluator = FakeEvaluator(CORRECT)
    env = make_env(evaluator)

    env.submit()

    assert evaluator.calls == [(CHALLENGE, SQL)]


# --- Infrastructure failures -------------------------------------------------


def test_evaluator_error_saves_nothing_and_raises_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cause = EvaluatorError("connection refused to sandbox at 10.0.0.5")
    env = make_env(FakeEvaluator(error=cause))

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(EvaluatorUnavailable) as raised,
    ):
        env.submit()

    env.assert_nothing_saved()
    assert raised.value.__cause__ is cause
    assert "10.0.0.5" not in str(raised.value)
    assert "connection refused to sandbox at 10.0.0.5" in caplog.text


def test_unexpected_exception_propagates_and_saves_nothing() -> None:
    env = make_env(FakeEvaluator(error=RuntimeError("bug in adapter")))

    with pytest.raises(RuntimeError, match="bug in adapter"):
        env.submit()

    env.assert_nothing_saved()


# --- Validation before any write --------------------------------------------


@pytest.mark.parametrize("sql", ["", "   ", "\n\t "])
def test_empty_submission_is_rejected_without_saving(sql: str) -> None:
    evaluator = FakeEvaluator(CORRECT)
    env = make_env(evaluator)

    with pytest.raises(EmptySubmission):
        env.submit(sql=sql)

    env.assert_nothing_saved()
    assert evaluator.calls == []


def test_unknown_challenge_is_rejected_without_saving() -> None:
    evaluator = FakeEvaluator(CORRECT)
    env = make_env(evaluator)

    with pytest.raises(ChallengeNotFound) as raised:
        env.submit(code="does-not-exist")

    assert raised.value.code == "does-not-exist"
    env.assert_nothing_saved()
    assert evaluator.calls == []


# --- Players, ids and clock -------------------------------------------------


def test_new_player_is_created_with_generated_id_and_clock_time() -> None:
    env = make_env(FakeEvaluator(CORRECT))

    env.submit()

    [player] = env.players.players
    assert player.roblox_user_id == ROBLOX_USER
    assert player.id == UUID(int=1)
    assert player.created_at == NOW
    [attempt] = env.attempts.attempts
    assert attempt.player_id == player.id


def test_attempt_uses_generated_id_and_clock_time() -> None:
    env = make_env(FakeEvaluator(CORRECT))

    env.submit()

    [attempt] = env.attempts.attempts
    assert attempt.id in env.ids.generated
    assert attempt.created_at == NOW


def test_existing_player_is_reused() -> None:
    existing = make_player(roblox_user_id=ROBLOX_USER)
    env = make_env(FakeEvaluator(CORRECT), players=[existing])

    env.submit()

    assert env.players.players == [existing]
    assert env.attempts.attempts[0].player_id == existing.id


def test_two_submissions_create_a_single_player() -> None:
    env = make_env(FakeEvaluator(CORRECT))

    env.submit()
    env.submit()

    assert len(env.players.players) == 1
    assert len(env.attempts.attempts) == 2


# --- UnitOfWork and race handling -------------------------------------------


def test_submit_solution_commits_unit_of_work() -> None:
    uow = FakeUnitOfWork()
    env = make_env(FakeEvaluator(CORRECT))
    env.uow = uow

    env.submit()

    assert uow.entered == 1
    assert uow.committed == 1
    assert uow.rolled_back == 0
    assert len(env.attempts.attempts) == 1


def test_evaluator_error_does_not_open_unit_of_work() -> None:
    uow = FakeUnitOfWork()
    env = make_env(FakeEvaluator(error=EvaluatorError("db down")))
    env.uow = uow

    with pytest.raises(EvaluatorUnavailable):
        env.submit()

    assert uow.entered == 0
    assert uow.committed == 0
    assert uow.rolled_back == 0


def test_write_failure_rolls_back_unit_of_work() -> None:
    class FailingAttemptRepo(InMemoryAttemptRepository):
        def add(self, attempt: Any) -> None:
            raise RuntimeError("disk full")

    uow = FakeUnitOfWork()
    env = make_env(FakeEvaluator(CORRECT))
    env.attempts = FailingAttemptRepo()
    env.uow = uow

    with pytest.raises(RuntimeError, match="disk full"):
        env.submit()

    assert uow.entered == 1
    assert uow.committed == 0
    assert uow.rolled_back == 1


def test_concurrent_first_submission_uses_persisted_player() -> None:
    winner = make_player(id=UUID(int=999), roblox_user_id=ROBLOX_USER)

    class RacingPlayerRepo(InMemoryPlayerRepository):
        def __init__(self) -> None:
            super().__init__()
            self._lookup_count = 0

        def get_by_roblox_user_id(self, roblox_user_id: int) -> Player | None:
            self._lookup_count += 1
            if self._lookup_count == 1:
                return None  # first check before concurrent insert wins
            return winner

        def add(self, player: Player) -> None:
            # Simulates INSERT ... ON CONFLICT DO NOTHING losing the race
            return None

    env = Env(evaluator=FakeEvaluator(CORRECT), players=RacingPlayerRepo())

    env.submit()

    [attempt] = env.attempts.attempts
    assert attempt.player_id == winner.id
