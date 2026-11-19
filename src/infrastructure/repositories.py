"""Concrete SQLAlchemy 2 repository implementations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from application.ports import AttemptRepository, ChallengeRepository, PlayerRepository
from domain.entities import Attempt, Challenge, Player
from infrastructure.orm import (
    AttemptModel,
    ChallengeModel,
    PlayerModel,
    attempt_from_domain,
    attempt_to_domain,
    challenge_to_domain,
    player_to_domain,
)
from infrastructure.serialization import serialize_expected_result


class SqlAlchemyPlayerRepository(PlayerRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_roblox_user_id(self, roblox_user_id: int) -> Player | None:
        stmt = select(PlayerModel).where(PlayerModel.roblox_user_id == roblox_user_id)
        model = self._session.scalar(stmt)
        return player_to_domain(model) if model is not None else None

    def add(self, player: Player) -> None:
        # Handle concurrent first-submission races without violating uniqueness.
        stmt = (
            pg_insert(PlayerModel)
            .values(
                id=player.id,
                roblox_user_id=player.roblox_user_id,
                created_at=player.created_at,
            )
            .on_conflict_do_nothing(index_elements=[PlayerModel.roblox_user_id])
        )
        self._session.execute(stmt)


class SqlAlchemyChallengeRepository(ChallengeRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[Challenge]:
        stmt = select(ChallengeModel).order_by(
            ChallengeModel.difficulty, ChallengeModel.code
        )
        models = self._session.scalars(stmt).all()
        return [challenge_to_domain(model) for model in models]

    def get_by_code(self, code: str) -> Challenge | None:
        stmt = select(ChallengeModel).where(ChallengeModel.code == code)
        model = self._session.scalar(stmt)
        return challenge_to_domain(model) if model is not None else None

    def upsert(self, challenge: Challenge) -> None:
        """Insert or update a challenge keyed by its unique code."""
        payload = {
            "id": challenge.id,
            "code": challenge.code,
            "module": challenge.module,
            "title": challenge.title,
            "description": challenge.description,
            "difficulty": int(challenge.difficulty),
            "setup_sql": challenge.setup_sql,
            "expected_result": serialize_expected_result(challenge.expected_result),
            "max_seconds": challenge.max_seconds,
            "ordered": challenge.ordered,
        }
        stmt = pg_insert(ChallengeModel).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ChallengeModel.code],
            set_={
                "module": stmt.excluded.module,
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "difficulty": stmt.excluded.difficulty,
                "setup_sql": stmt.excluded.setup_sql,
                "expected_result": stmt.excluded.expected_result,
                "max_seconds": stmt.excluded.max_seconds,
                "ordered": stmt.excluded.ordered,
            },
        )
        self._session.execute(stmt)


class SqlAlchemyAttemptRepository(AttemptRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: Attempt) -> None:
        self._session.add(attempt_from_domain(attempt))
        self._session.flush()

    def list_by_player(self, player_id: UUID) -> list[Attempt]:
        stmt = (
            select(AttemptModel)
            .where(AttemptModel.player_id == player_id)
            .order_by(AttemptModel.created_at, AttemptModel.id)
        )
        models = self._session.scalars(stmt).all()
        return [attempt_to_domain(model) for model in models]
