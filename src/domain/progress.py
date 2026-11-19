"""Player progress, derived from attempts (SPEC section 5)."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from domain.entities import Attempt
from domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class Progress:
    player_id: UUID
    challenge_id: UUID
    completed_at: datetime
    best_ms: int


def compute_progress(player_id: UUID, attempts: Iterable[Attempt]) -> list[Progress]:
    """Summarize completed challenges, sorted by completed_at then challenge_id.

    ``completed_at`` is the first successful attempt; ``best_ms`` is the fastest
    successful attempt. Failed attempts never count.
    """
    passed_by_challenge: dict[UUID, list[Attempt]] = defaultdict(list)
    for attempt in attempts:
        if attempt.player_id != player_id:
            raise DomainValidationError("attempt belongs to another player")
        if attempt.passed:
            passed_by_challenge[attempt.challenge_id].append(attempt)
    progress = [
        _summarize(player_id, challenge_id, passed)
        for challenge_id, passed in passed_by_challenge.items()
    ]
    return sorted(progress, key=lambda item: (item.completed_at, item.challenge_id))


def _summarize(player_id: UUID, challenge_id: UUID, passed: list[Attempt]) -> Progress:
    first = min(passed, key=lambda attempt: attempt.created_at)
    best_ms = min(a.execution_ms for a in passed if a.execution_ms is not None)
    return Progress(player_id, challenge_id, first.created_at, best_ms)
