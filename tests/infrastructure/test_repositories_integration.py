"""Integration tests against a dedicated PostgreSQL test database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from application.evaluation import ExecutionFailed, ExecutionSucceeded
from application.ports import SolutionEvaluator
from application.use_cases.get_progress import GetProgress
from application.use_cases.submit_solution import SubmitSolution
from domain.entities import Attempt, Challenge, Difficulty, Player
from infrastructure.config import get_database_url
from infrastructure.repositories import (
    SqlAlchemyAttemptRepository,
    SqlAlchemyChallengeRepository,
    SqlAlchemyPlayerRepository,
)
from infrastructure.system import UtcClock, Uuid4Generator
from infrastructure.uow import SqlAlchemyUnitOfWork

NOW = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)


class _StubEvaluator(SolutionEvaluator):
    def __init__(self, outcome: ExecutionSucceeded | ExecutionFailed) -> None:
        self._outcome = outcome

    def evaluate(
        self, challenge: Challenge, sql: str
    ) -> ExecutionSucceeded | ExecutionFailed:
        return self._outcome


def test_integration_uses_separate_test_database(db_session: Session) -> None:
    test_db = db_session.get_bind().url.database  # type: ignore[union-attr]
    dev_db = make_url(get_database_url()).database

    assert test_db is not None
    assert test_db != dev_db
    assert test_db.endswith("_test")


def test_player_repository_add_get_and_conflict_handling(db_session: Session) -> None:
    repo = SqlAlchemyPlayerRepository(db_session)
    assert repo.get_by_roblox_user_id(1001) is None

    first = Player(id=uuid4(), roblox_user_id=1001, created_at=NOW)
    duplicate = Player(
        id=uuid4(), roblox_user_id=1001, created_at=NOW + timedelta(seconds=10)
    )

    repo.add(first)
    repo.add(duplicate)  # ON CONFLICT DO NOTHING must not raise
    db_session.commit()

    loaded = repo.get_by_roblox_user_id(1001)
    assert loaded == first


def test_challenge_repository_round_trip_and_ordering(db_session: Session) -> None:
    repo = SqlAlchemyChallengeRepository(db_session)
    hard = Challenge(
        id=uuid4(),
        code="z-hard",
        module="postgresql",
        title="Reto difícil",
        description="Descripción",
        difficulty=Difficulty.HARD,
        setup_sql="CREATE TABLE t (id int);",
        expected_result=((1, Decimal("42.5000"), True, None),),
        max_seconds=3.0,
        ordered=True,
    )
    easy_b = Challenge(
        id=uuid4(),
        code="b-easy",
        module="postgresql",
        title="Reto fácil B",
        description="Descripción",
        difficulty=Difficulty.EASY,
        setup_sql="SELECT 1;",
        expected_result=((1, "1.0"),),
        max_seconds=2.0,
    )
    easy_a = Challenge(
        id=uuid4(),
        code="a-easy",
        module="postgresql",
        title="Reto fácil A",
        description="Descripción",
        difficulty=Difficulty.EASY,
        setup_sql="SELECT 1;",
        expected_result=(),
        max_seconds=2.0,
    )

    for ch in (hard, easy_b, easy_a):
        repo.upsert(ch)
    db_session.commit()

    assert [c.code for c in repo.list_all()] == ["a-easy", "b-easy", "z-hard"]
    loaded_hard = repo.get_by_code("z-hard")
    assert loaded_hard == hard
    assert loaded_hard is not None
    assert type(loaded_hard.expected_result[0][1]) is Decimal
    assert type(loaded_hard.expected_result[0][2]) is bool
    assert repo.get_by_code("missing") is None


def test_attempt_repository_persists_and_filters_by_player(
    db_session: Session,
) -> None:
    players = SqlAlchemyPlayerRepository(db_session)
    challenges = SqlAlchemyChallengeRepository(db_session)
    attempts = SqlAlchemyAttemptRepository(db_session)

    p1 = Player(id=uuid4(), roblox_user_id=2001, created_at=NOW)
    p2 = Player(id=uuid4(), roblox_user_id=2002, created_at=NOW)
    ch = Challenge(
        id=uuid4(),
        code="c1",
        module="postgresql",
        title="Reto 1",
        description="Desc",
        difficulty=Difficulty.EASY,
        setup_sql="SELECT 1;",
        expected_result=((1,),),
        max_seconds=2.0,
    )
    players.add(p1)
    players.add(p2)
    challenges.upsert(ch)
    db_session.flush()

    a1 = Attempt(
        id=uuid4(),
        player_id=p1.id,
        challenge_id=ch.id,
        submitted_sql="SELEC 1;",
        passed=False,
        execution_ms=None,
        error_message="syntax error",
        created_at=NOW,
    )
    a2 = Attempt(
        id=uuid4(),
        player_id=p1.id,
        challenge_id=ch.id,
        submitted_sql="SELECT 1;",
        passed=True,
        execution_ms=12,
        error_message=None,
        created_at=NOW + timedelta(seconds=5),
    )
    a_other = Attempt(
        id=uuid4(),
        player_id=p2.id,
        challenge_id=ch.id,
        submitted_sql="SELECT 1;",
        passed=True,
        execution_ms=8,
        error_message=None,
        created_at=NOW,
    )

    for attempt in (a2, a_other, a1):
        attempts.add(attempt)
    db_session.commit()

    assert attempts.list_by_player(p1.id) == [a1, a2]
    assert attempts.list_by_player(p2.id) == [a_other]


def test_unit_of_work_rolls_back_on_exception(
    session_factory: sessionmaker[Session],
) -> None:
    player_id = uuid4()
    with session_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        players = SqlAlchemyPlayerRepository(session)
        with pytest.raises(RuntimeError, match="boom"):
            with uow:
                players.add(Player(id=player_id, roblox_user_id=3001, created_at=NOW))
                raise RuntimeError("boom")

    with session_factory() as verify_session:
        assert (
            SqlAlchemyPlayerRepository(verify_session).get_by_roblox_user_id(3001)
            is None
        )


def test_submit_solution_and_get_progress_end_to_end(
    session_factory: sessionmaker[Session],
) -> None:
    challenge = Challenge(
        id=uuid4(),
        code="dedupe",
        module="postgresql",
        title="Duplicados",
        description="Elimina duplicados",
        difficulty=Difficulty.EASY,
        setup_sql="CREATE TABLE t (id int);",
        expected_result=((1, "Ana"),),
        max_seconds=2.0,
    )
    with session_factory() as seed_session:
        SqlAlchemyChallengeRepository(seed_session).upsert(challenge)
        seed_session.commit()

    with session_factory() as write_session:
        submit = SubmitSolution(
            players=SqlAlchemyPlayerRepository(write_session),
            challenges=SqlAlchemyChallengeRepository(write_session),
            attempts=SqlAlchemyAttemptRepository(write_session),
            evaluator=_StubEvaluator(
                ExecutionSucceeded(rows=((1, "Ana"),), execution_ms=19)
            ),
            clock=UtcClock(),
            ids=Uuid4Generator(),
            uow=SqlAlchemyUnitOfWork(write_session),
        )
        result = submit.execute(
            roblox_user_id=4001, code="dedupe", sql="SELECT 1, 'Ana';"
        )
        assert result.passed is True

    with session_factory() as read_session:
        progress = GetProgress(
            players=SqlAlchemyPlayerRepository(read_session),
            challenges=SqlAlchemyChallengeRepository(read_session),
            attempts=SqlAlchemyAttemptRepository(read_session),
        ).execute(4001)

    assert progress.roblox_user_id == 4001
    assert len(progress.completed) == 1
    assert progress.completed[0].code == "dedupe"
    assert progress.completed[0].best_ms == 19
    assert isinstance(UUID(int=1), UUID)
