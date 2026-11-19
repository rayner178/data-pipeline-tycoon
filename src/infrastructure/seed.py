"""Idempotent seed loading challenges from the declarative ``challenges/`` catalog."""

from sqlalchemy.orm import Session, sessionmaker

from domain.entities import Challenge
from infrastructure.challenge_loader import load_all_challenges
from infrastructure.db import create_db_engine
from infrastructure.repositories import SqlAlchemyChallengeRepository

MVP_CHALLENGES: tuple[Challenge, ...] = load_all_challenges()


def seed_mvp_challenges(session: Session) -> list[Challenge]:
    """Insert or update all declarative challenges idempotently."""
    challenges = load_all_challenges()
    repository = SqlAlchemyChallengeRepository(session)
    for challenge in challenges:
        repository.upsert(challenge)
    session.commit()
    return list(challenges)


def main() -> None:
    engine = create_db_engine()
    try:
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as session:
            seed_mvp_challenges(session)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
