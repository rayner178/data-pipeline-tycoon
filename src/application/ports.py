"""Ports: abstract interfaces implemented by the infrastructure layer."""

from abc import ABC, abstractmethod
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from application.evaluation import EvaluationResult
from domain.entities import Attempt, Challenge, Player


class PlayerRepository(ABC):
    @abstractmethod
    def get_by_roblox_user_id(self, roblox_user_id: int) -> Player | None: ...

    @abstractmethod
    def add(self, player: Player) -> None: ...


class ChallengeRepository(ABC):
    @abstractmethod
    def list_all(self) -> list[Challenge]: ...

    @abstractmethod
    def get_by_code(self, code: str) -> Challenge | None: ...


class AttemptRepository(ABC):
    @abstractmethod
    def add(self, attempt: Attempt) -> None: ...

    @abstractmethod
    def list_by_player(self, player_id: UUID) -> list[Attempt]: ...


class SolutionEvaluator(ABC):
    @abstractmethod
    def evaluate(self, challenge: Challenge, sql: str) -> EvaluationResult:
        """Run the player's SQL for ``challenge`` and report what happened.

        Errors in the player's SQL are returned as ``ExecutionFailed``.
        Infrastructure failures must be raised as ``EvaluatorError`` only.
        """


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime."""


class IdGenerator(ABC):
    @abstractmethod
    def new_id(self) -> UUID: ...


class UnitOfWork(ABC):
    """Transaction boundary around write operations."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollback()

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...
