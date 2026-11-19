"""SubmitSolution use case."""

import logging
from dataclasses import dataclass
from datetime import datetime

from application.dto import SubmissionResult
from application.errors import (
    ChallengeNotFound,
    EmptySubmission,
    EvaluatorError,
    EvaluatorUnavailable,
)
from application.evaluation import EvaluationResult, ExecutionFailed
from application.ports import (
    AttemptRepository,
    ChallengeRepository,
    Clock,
    IdGenerator,
    PlayerRepository,
    SolutionEvaluator,
    UnitOfWork,
)
from domain.entities import Attempt, Challenge, Player
from domain.errors import DomainValidationError
from domain.execution_plan import plan_uses_index

logger = logging.getLogger(__name__)

MESSAGE_SOLVED = "¡Reto superado!"
MESSAGE_MISMATCH = "El resultado no coincide con el esperado."
MESSAGE_INCOMPARABLE = "El resultado contiene valores que no se pueden comparar."
MESSAGE_INDEX_NOT_USED = (
    "El resultado es correcto, pero el plan de ejecución no utiliza el índice esperado."
)


@dataclass(frozen=True, slots=True)
class _Outcome:
    passed: bool
    execution_ms: int | None
    error_message: str | None
    message: str


class SubmitSolution:
    """Evaluate a player's SQL for a challenge and always record the attempt.

    Nothing is written for an empty submission, an unknown challenge or an
    evaluator infrastructure failure. Phase 3: player creation and the attempt
    insert should share one short transaction; evaluation stays outside it.
    """

    def __init__(
        self,
        *,
        players: PlayerRepository,
        challenges: ChallengeRepository,
        attempts: AttemptRepository,
        evaluator: SolutionEvaluator,
        clock: Clock,
        ids: IdGenerator,
        uow: UnitOfWork | None = None,
    ) -> None:
        self._players = players
        self._challenges = challenges
        self._attempts = attempts
        self._evaluator = evaluator
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def execute(self, *, roblox_user_id: int, code: str, sql: str) -> SubmissionResult:
        if not sql.strip():
            raise EmptySubmission()
        challenge = self._challenges.get_by_code(code)
        if challenge is None:
            raise ChallengeNotFound(code)
        outcome = _judge(challenge, self._evaluate(challenge, sql))
        now = self._clock.now()
        self._persist_attempt(roblox_user_id, challenge, sql, outcome, now)
        return SubmissionResult(
            passed=outcome.passed,
            execution_ms=outcome.execution_ms,
            message=outcome.message,
        )

    def _persist_attempt(
        self,
        roblox_user_id: int,
        challenge: Challenge,
        sql: str,
        outcome: _Outcome,
        now: datetime,
    ) -> None:
        if self._uow is None:
            player = self._get_or_create_player(roblox_user_id, now)
            self._attempts.add(
                self._build_attempt(player, challenge, sql, outcome, now)
            )
            return
        with self._uow:
            player = self._get_or_create_player(roblox_user_id, now)
            self._attempts.add(
                self._build_attempt(player, challenge, sql, outcome, now)
            )
            self._uow.commit()

    def _evaluate(self, challenge: Challenge, sql: str) -> EvaluationResult:
        try:
            return self._evaluator.evaluate(challenge, sql)
        except EvaluatorError as exc:
            logger.exception("Evaluator failed for challenge %s", challenge.code)
            raise EvaluatorUnavailable() from exc

    def _get_or_create_player(self, roblox_user_id: int, now: datetime) -> Player:
        player = self._players.get_by_roblox_user_id(roblox_user_id)
        if player is None:
            candidate = Player(
                id=self._ids.new_id(), roblox_user_id=roblox_user_id, created_at=now
            )
            self._players.add(candidate)
            # Re-read so a concurrent ON CONFLICT DO NOTHING winner is used if present.
            player = self._players.get_by_roblox_user_id(roblox_user_id) or candidate
        return player

    def _build_attempt(
        self,
        player: Player,
        challenge: Challenge,
        sql: str,
        outcome: _Outcome,
        now: datetime,
    ) -> Attempt:
        return Attempt(
            id=self._ids.new_id(),
            player_id=player.id,
            challenge_id=challenge.id,
            submitted_sql=sql,
            passed=outcome.passed,
            execution_ms=outcome.execution_ms,
            error_message=outcome.error_message,
            created_at=now,
        )


def _judge(challenge: Challenge, evaluation: EvaluationResult) -> _Outcome:
    if isinstance(evaluation, ExecutionFailed):
        message = evaluation.error_message
        return _Outcome(False, evaluation.execution_ms, message, message)
    try:
        solved = challenge.is_solved_by(evaluation.rows)
    except DomainValidationError:
        return _Outcome(
            False, evaluation.execution_ms, MESSAGE_INCOMPARABLE, MESSAGE_INCOMPARABLE
        )
    if not solved:
        return _Outcome(False, evaluation.execution_ms, None, MESSAGE_MISMATCH)
    if challenge.requires_index_plan() and (
        evaluation.plan is None or not plan_uses_index(evaluation.plan)
    ):
        return _Outcome(False, evaluation.execution_ms, None, MESSAGE_INDEX_NOT_USED)
    return _Outcome(True, evaluation.execution_ms, None, MESSAGE_SOLVED)
