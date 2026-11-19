"""SQLAlchemy 2 ORM models and explicit mapping to/from domain entities."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain.entities import Attempt, Challenge, Difficulty, Player
from infrastructure.serialization import (
    deserialize_expected_result,
    serialize_expected_result,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class PlayerModel(Base):
    __tablename__ = "players"
    __table_args__ = (
        UniqueConstraint("roblox_user_id", name="uq_players_roblox_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    roblox_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ChallengeModel(Base):
    __tablename__ = "challenges"
    __table_args__ = (
        UniqueConstraint("code", name="uq_challenges_code"),
        Index("ix_challenges_difficulty_code", "difficulty", "code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    setup_sql: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[list[list[Any]]] = mapped_column(JSONB, nullable=False)
    max_seconds: Mapped[float] = mapped_column(Double, nullable=False)
    ordered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class AttemptModel(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        Index("ix_attempts_player_id", "player_id"),
        Index("ix_attempts_challenge_id", "challenge_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    player_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("players.id", ondelete="RESTRICT"),
        nullable=False,
    )
    challenge_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("challenges.id", ondelete="RESTRICT"),
        nullable=False,
    )
    submitted_sql: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    execution_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def player_to_domain(model: PlayerModel) -> Player:
    return Player(
        id=model.id,
        roblox_user_id=model.roblox_user_id,
        created_at=model.created_at,
    )


def player_from_domain(entity: Player) -> PlayerModel:
    return PlayerModel(
        id=entity.id,
        roblox_user_id=entity.roblox_user_id,
        created_at=entity.created_at,
    )


def challenge_to_domain(model: ChallengeModel) -> Challenge:
    return Challenge(
        id=model.id,
        code=model.code,
        module=model.module,
        title=model.title,
        description=model.description,
        difficulty=Difficulty(model.difficulty),
        setup_sql=model.setup_sql,
        expected_result=deserialize_expected_result(model.expected_result),
        max_seconds=model.max_seconds,
        ordered=model.ordered,
    )


def challenge_from_domain(entity: Challenge) -> ChallengeModel:
    return ChallengeModel(
        id=entity.id,
        code=entity.code,
        module=entity.module,
        title=entity.title,
        description=entity.description,
        difficulty=int(entity.difficulty),
        setup_sql=entity.setup_sql,
        expected_result=serialize_expected_result(entity.expected_result),
        max_seconds=entity.max_seconds,
        ordered=entity.ordered,
    )


def attempt_to_domain(model: AttemptModel) -> Attempt:
    return Attempt(
        id=model.id,
        player_id=model.player_id,
        challenge_id=model.challenge_id,
        submitted_sql=model.submitted_sql,
        passed=model.passed,
        execution_ms=model.execution_ms,
        error_message=model.error_message,
        created_at=model.created_at,
    )


def attempt_from_domain(entity: Attempt) -> AttemptModel:
    return AttemptModel(
        id=entity.id,
        player_id=entity.player_id,
        challenge_id=entity.challenge_id,
        submitted_sql=entity.submitted_sql,
        passed=entity.passed,
        execution_ms=entity.execution_ms,
        error_message=entity.error_message,
        created_at=entity.created_at,
    )
