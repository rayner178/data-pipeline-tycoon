"""Tests for PostgreSQL execution plan rules in the domain layer."""

import pytest

from domain.execution_plan import plan_uses_index
from tests.domain.factories import make_challenge


@pytest.mark.parametrize(
    "plan",
    [
        (
            "Index Scan using idx_events_user_created on events\n"
            "  Index Cond: (user_id = 42)"
        ),
        (
            "Index Only Scan using idx_events_user_created on events\n"
            "  Index Cond: (user_id = 42)"
        ),
        (
            "Bitmap Heap Scan on events\n"
            "  ->  Bitmap Index Scan on idx_events_user_created"
        ),
    ],
)
def test_plan_uses_index_accepts_index_scans(plan: str) -> None:
    assert plan_uses_index(plan) is True


@pytest.mark.parametrize(
    "plan",
    [
        "",
        "Seq Scan on events\n  Filter: ((user_id)::text = '42'::text)",
        "Result",
        "Sort\n  ->  Seq Scan on events",
    ],
)
def test_plan_uses_index_rejects_sequential_or_empty_plans(plan: str) -> None:
    assert plan_uses_index(plan) is False


def test_challenge_requires_index_plan_when_setup_creates_index() -> None:
    indexed = make_challenge(
        setup_sql=(
            "CREATE TABLE events (id INT, user_id INT);\n"
            "CREATE INDEX idx_events_user ON events (user_id);"
        )
    )
    unique_indexed = make_challenge(
        setup_sql=(
            "CREATE TABLE events (id INT, user_id INT);\n"
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_id ON events (id);"
        )
    )
    plain = make_challenge(setup_sql="CREATE TABLE customers (id INT, name TEXT);")

    assert indexed.requires_index_plan() is True
    assert unique_indexed.requires_index_plan() is True
    assert plain.requires_index_plan() is False
