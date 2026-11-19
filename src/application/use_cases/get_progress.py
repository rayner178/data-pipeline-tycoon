"""GetProgress use case."""

from application.dto import CompletedChallenge, PlayerProgress
from application.ports import AttemptRepository, ChallengeRepository, PlayerRepository
from domain.progress import compute_progress


class GetProgress:
    def __init__(
        self,
        *,
        players: PlayerRepository,
        challenges: ChallengeRepository,
        attempts: AttemptRepository,
    ) -> None:
        self._players = players
        self._challenges = challenges
        self._attempts = attempts

    def execute(self, roblox_user_id: int) -> PlayerProgress:
        """Return completed challenges; an unknown player gets empty progress.

        Read-only: an unknown player is not created. Progress for a challenge
        that no longer exists in the repository is omitted.
        """
        player = self._players.get_by_roblox_user_id(roblox_user_id)
        if player is None:
            return PlayerProgress(roblox_user_id=roblox_user_id, completed=())
        progress = compute_progress(player.id, self._attempts.list_by_player(player.id))
        codes = {
            challenge.id: challenge.code for challenge in self._challenges.list_all()
        }
        completed = tuple(
            CompletedChallenge(
                code=codes[item.challenge_id],
                completed_at=item.completed_at,
                best_ms=item.best_ms,
            )
            for item in progress
            if item.challenge_id in codes
        )
        return PlayerProgress(roblox_user_id=roblox_user_id, completed=completed)
