"""FastAPI dependency injection wiring application ports to adapters."""

import functools
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from application.errors import EvaluatorError
from application.evaluation import EvaluationResult
from application.ports import SolutionEvaluator
from application.use_cases.get_progress import GetProgress
from application.use_cases.list_challenges import ListChallenges
from application.use_cases.submit_solution import SubmitSolution
from domain.entities import Challenge
from infrastructure.config import get_api_key
from infrastructure.db import create_db_engine
from infrastructure.repositories import (
    SqlAlchemyAttemptRepository,
    SqlAlchemyChallengeRepository,
    SqlAlchemyPlayerRepository,
)
from infrastructure.system import UtcClock, Uuid4Generator
from infrastructure.uow import SqlAlchemyUnitOfWork


class _UnconfiguredEvaluator(SolutionEvaluator):
    def evaluate(self, challenge: Challenge, sql: str) -> EvaluationResult:
        raise EvaluatorError("SQL sandbox evaluator is not configured yet (phase 5)")


def get_configured_api_key() -> str:
    return get_api_key()


@functools.lru_cache(maxsize=1)
def get_db_engine() -> Engine:
    return create_db_engine()


def get_db_session(
    engine: Annotated[Engine, Depends(get_db_engine)],
) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def get_solution_evaluator() -> SolutionEvaluator:
    return _UnconfiguredEvaluator()


def get_list_challenges_use_case(
    session: Annotated[Session, Depends(get_db_session)],
) -> ListChallenges:
    return ListChallenges(SqlAlchemyChallengeRepository(session))


def get_submit_solution_use_case(
    session: Annotated[Session, Depends(get_db_session)],
    evaluator: Annotated[SolutionEvaluator, Depends(get_solution_evaluator)],
) -> SubmitSolution:
    return SubmitSolution(
        players=SqlAlchemyPlayerRepository(session),
        challenges=SqlAlchemyChallengeRepository(session),
        attempts=SqlAlchemyAttemptRepository(session),
        evaluator=evaluator,
        clock=UtcClock(),
        ids=Uuid4Generator(),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_progress_use_case(
    session: Annotated[Session, Depends(get_db_session)],
) -> GetProgress:
    return GetProgress(
        players=SqlAlchemyPlayerRepository(session),
        challenges=SqlAlchemyChallengeRepository(session),
        attempts=SqlAlchemyAttemptRepository(session),
    )
