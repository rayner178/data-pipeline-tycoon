"""ListChallenges use case."""

from application.dto import ChallengeSummary
from application.ports import ChallengeRepository
from domain.entities import Challenge


class ListChallenges:
    def __init__(self, challenges: ChallengeRepository) -> None:
        self._challenges = challenges

    def execute(self) -> list[ChallengeSummary]:
        """Return public challenge summaries sorted by difficulty, then code."""
        ordered = sorted(
            self._challenges.list_all(), key=lambda c: (c.difficulty, c.code)
        )
        return [_summarize(challenge) for challenge in ordered]


def _summarize(challenge: Challenge) -> ChallengeSummary:
    return ChallengeSummary(
        code=challenge.code,
        module=challenge.module,
        title=challenge.title,
        description=challenge.description,
        difficulty=challenge.difficulty,
    )
