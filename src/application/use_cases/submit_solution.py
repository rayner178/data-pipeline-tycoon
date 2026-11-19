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
from application.evaluation import (
    EvaluationResult,
    ExecutionFailed,
    ExecutionSucceeded,
)
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
from domain.result_matching import Cell, FrozenResult, results_match

logger = logging.getLogger(__name__)

MAX_PREVIEW_ROWS = 10
MAX_PREVIEW_CELL_LENGTH = 120

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
    columns: tuple[str, ...] = ()
    preview_rows: tuple[tuple[str, ...], ...] = ()


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
            columns=outcome.columns,
            preview_rows=outcome.preview_rows,
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
    preview = _build_preview_rows(evaluation.rows)
    try:
        solved = challenge.is_solved_by(evaluation.rows)
    except DomainValidationError:
        return _Outcome(
            False,
            evaluation.execution_ms,
            MESSAGE_INCOMPARABLE,
            MESSAGE_INCOMPARABLE,
            columns=evaluation.columns,
            preview_rows=preview,
        )
    if not solved:
        return _Outcome(
            False,
            evaluation.execution_ms,
            None,
            _diagnose_mismatch(challenge, evaluation),
            columns=evaluation.columns,
            preview_rows=preview,
        )
    if challenge.requires_index_plan() and (
        evaluation.plan is None or not plan_uses_index(evaluation.plan)
    ):
        return _Outcome(
            False,
            evaluation.execution_ms,
            None,
            MESSAGE_INDEX_NOT_USED,
            columns=evaluation.columns,
            preview_rows=preview,
        )
    return _Outcome(
        True,
        evaluation.execution_ms,
        None,
        MESSAGE_SOLVED,
        columns=evaluation.columns,
        preview_rows=preview,
    )


def _diagnose_mismatch(challenge: Challenge, evaluation: ExecutionSucceeded) -> str:
    expected = challenge.expected_result
    actual = evaluation.rows
    expected_cols = len(expected[0]) if expected else 0
    actual_cols = len(actual[0]) if actual else len(evaluation.columns)
    if expected_cols > 0 and actual_cols > 0 and actual_cols != expected_cols:
        return (
            f"{MESSAGE_MISMATCH} Tu consulta devolvió {actual_cols} columna(s), "
            f"pero se esperaban {expected_cols}."
        )
    if len(actual) != len(expected):
        return (
            f"{MESSAGE_MISMATCH} Tu consulta devolvió {len(actual)} fila(s), "
            f"pero se esperaban {len(expected)}."
        )
    if challenge.ordered and results_match(actual, expected, ordered=False):
        return (
            f"{MESSAGE_MISMATCH} Las filas devueltas son correctas, "
            "pero el orden no coincide (revisa el ORDER BY)."
        )
    return (
        f"{MESSAGE_MISMATCH} La cantidad de filas y columnas es correcta, "
        "pero los valores no coinciden."
    )


def _build_preview_rows(rows: FrozenResult) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(_format_preview_cell(cell) for cell in row)
        for row in rows[:MAX_PREVIEW_ROWS]
    )


def _format_preview_cell(cell: Cell) -> str:
    if cell is None:
        return "NULL"
    if isinstance(cell, bool):
        return "true" if cell else "false"
    text = str(cell)
    if len(text) > MAX_PREVIEW_CELL_LENGTH:
        return text[: MAX_PREVIEW_CELL_LENGTH - 3] + "..."
    return text
