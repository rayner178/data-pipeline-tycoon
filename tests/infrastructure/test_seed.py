"""Integration tests for the idempotent MVP challenge seed."""

from sqlalchemy.orm import Session

from application.use_cases.list_challenges import ListChallenges
from domain.entities import Difficulty
from infrastructure.repositories import SqlAlchemyChallengeRepository
from infrastructure.seed import MVP_CHALLENGES, seed_mvp_challenges


def test_mvp_challenges_definition_covers_three_increasing_difficulties() -> None:
    assert len(MVP_CHALLENGES) == 3
    assert [c.difficulty for c in MVP_CHALLENGES] == [
        Difficulty.EASY,
        Difficulty.MEDIUM,
        Difficulty.HARD,
    ]
    assert [c.code for c in MVP_CHALLENGES] == [
        "dedupe-row-number",
        "fix-multiplying-join",
        "index-slow-query",
    ]


def test_seed_mvp_challenges_inserts_and_is_idempotent(db_session: Session) -> None:
    first = seed_mvp_challenges(db_session)
    second = seed_mvp_challenges(db_session)

    repo = SqlAlchemyChallengeRepository(db_session)
    stored = repo.list_all()
    summaries = ListChallenges(repo).execute()

    assert len(first) == 3
    assert len(second) == 3
    assert [c.code for c in stored] == [
        "dedupe-row-number",
        "fix-multiplying-join",
        "index-slow-query",
    ]
    assert [s.code for s in summaries] == [
        "dedupe-row-number",
        "fix-multiplying-join",
        "index-slow-query",
    ]
