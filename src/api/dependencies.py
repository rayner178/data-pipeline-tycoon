"""FastAPI dependency injection wiring application ports to adapters."""

import functools
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from application.ports import SolutionEvaluator
from application.use_cases.get_progress import GetProgress
from application.use_cases.list_challenges import ListChallenges
from application.use_cases.submit_solution import SubmitSolution
from infrastructure.config import get_api_key, get_sandbox_database_url
from infrastructure.db import create_db_engine, resolve_database_url
from infrastructure.repositories import (
    SqlAlchemyAttemptRepository,
    SqlAlchemyChallengeRepository,
    SqlAlchemyPlayerRepository,
)
from infrastructure.sandbox import PostgresSandboxEvaluator
from infrastructure.system import UtcClock, Uuid4Generator
from infrastructure.uow import SqlAlchemyUnitOfWork


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


@functools.lru_cache(maxsize=1)
def _cached_sandbox_evaluator() -> PostgresSandboxEvaluator:
    raw_sandbox_url = get_sandbox_database_url()
    sandbox_url = (
        resolve_database_url(raw_sandbox_url) if raw_sandbox_url is not None else None
    )
    return PostgresSandboxEvaluator(
        get_db_engine(),
        sandbox_database_url=sandbox_url,
    )


def get_solution_evaluator() -> SolutionEvaluator:
    return _cached_sandbox_evaluator()


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
