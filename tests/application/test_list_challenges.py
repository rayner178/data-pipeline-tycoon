"""Tests for the ListChallenges use case."""

from application.dto import ChallengeSummary
from application.use_cases.list_challenges import ListChallenges
from domain.entities import Difficulty
from tests.application.fakes import InMemoryChallengeRepository
from tests.domain.factories import make_challenge


def test_empty_repository_gives_empty_list() -> None:
    assert ListChallenges(InMemoryChallengeRepository()).execute() == []


def test_challenges_are_sorted_by_difficulty_then_code() -> None:
    repository = InMemoryChallengeRepository(
        [
            make_challenge(code="c", difficulty=Difficulty.HARD),
            make_challenge(code="b", difficulty=Difficulty.EASY),
            make_challenge(code="d", difficulty=Difficulty.MEDIUM),
            make_challenge(code="a", difficulty=Difficulty.EASY),
        ]
    )

    summaries = ListChallenges(repository).execute()

    assert [s.code for s in summaries] == ["a", "b", "d", "c"]


def test_summary_contains_public_fields() -> None:
    challenge = make_challenge(code="dedupe", difficulty=Difficulty.MEDIUM)

    summaries = ListChallenges(InMemoryChallengeRepository([challenge])).execute()

    assert summaries == [
        ChallengeSummary(
            code="dedupe",
            module=challenge.module,
            title=challenge.title,
            description=challenge.description,
            difficulty=Difficulty.MEDIUM,
        )
    ]


def test_summary_does_not_expose_solution_or_setup() -> None:
    repository = InMemoryChallengeRepository([make_challenge()])

    summary = ListChallenges(repository).execute()[0]

    assert not hasattr(summary, "expected_result")
    assert not hasattr(summary, "setup_sql")
