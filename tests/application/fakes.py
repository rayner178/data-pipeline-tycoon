"""In-memory test doubles for the application ports."""

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from application.evaluation import EvaluationResult
from application.ports import (
    AttemptRepository,
    ChallengeRepository,
    Clock,
    IdGenerator,
    PlayerRepository,
    SolutionEvaluator,
)
from domain.entities import Attempt, Challenge, Player
from tests.domain.factories import NOW


class InMemoryPlayerRepository(PlayerRepository):
    def __init__(self, players: Iterable[Player] = ()) -> None:
        self.players: list[Player] = list(players)

    def get_by_roblox_user_id(self, roblox_user_id: int) -> Player | None:
        return next(
            (p for p in self.players if p.roblox_user_id == roblox_user_id), None
        )

    def add(self, player: Player) -> None:
        self.players.append(player)


class InMemoryChallengeRepository(ChallengeRepository):
    def __init__(self, challenges: Iterable[Challenge] = ()) -> None:
        self.challenges: list[Challenge] = list(challenges)

    def list_all(self) -> list[Challenge]:
        return list(self.challenges)

    def get_by_code(self, code: str) -> Challenge | None:
        return next((c for c in self.challenges if c.code == code), None)


class InMemoryAttemptRepository(AttemptRepository):
    def __init__(self, attempts: Iterable[Attempt] = ()) -> None:
        self.attempts: list[Attempt] = list(attempts)

    def add(self, attempt: Attempt) -> None:
        self.attempts.append(attempt)

    def list_by_player(self, player_id: UUID) -> list[Attempt]:
        return [a for a in self.attempts if a.player_id == player_id]


class FakeEvaluator(SolutionEvaluator):
    """Returns a preset result, or raises a preset exception."""

    def __init__(
        self,
        result: EvaluationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[Challenge, str]] = []

    def evaluate(self, challenge: Challenge, sql: str) -> EvaluationResult:
        self.calls.append((challenge, sql))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("FakeEvaluator has no result configured")
        return self.result


class FixedClock(Clock):
    def __init__(self, now: datetime = NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class SequentialIdGenerator(IdGenerator):
    """Yields UUID(int=1), UUID(int=2), ... in order."""

    def __init__(self) -> None:
        self.generated: list[UUID] = []

    def new_id(self) -> UUID:
        new = UUID(int=len(self.generated) + 1)
        self.generated.append(new)
        return new
