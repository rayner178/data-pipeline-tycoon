"""Security and functional tests for the PostgreSQL SQL sandbox and MVP challenges."""

import re
import time
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from api.schemas import MAX_SQL_LENGTH
from application.errors import EvaluatorError
from application.evaluation import ExecutionFailed, ExecutionSucceeded
from application.use_cases.submit_solution import (
    MESSAGE_INDEX_NOT_USED,
    MESSAGE_SOLVED,
    SubmitSolution,
)
from domain.entities import Challenge, Difficulty
from infrastructure.repositories import (
    SqlAlchemyAttemptRepository,
    SqlAlchemyChallengeRepository,
    SqlAlchemyPlayerRepository,
)
from infrastructure.sandbox import (
    MAX_RESULT_ROWS,
    SANDBOX_ROLE,
    PostgresSandboxEvaluator,
    validate_single_select_sql,
)
from infrastructure.seed import MVP_CHALLENGES
from infrastructure.system import UtcClock, Uuid4Generator
from infrastructure.uow import SqlAlchemyUnitOfWork

SAFE_CHALLENGE = Challenge(
    id=uuid4(),
    code="sandbox-target",
    module="postgresql",
    title="Sandbox probe",
    description="Probe",
    difficulty=Difficulty.EASY,
    setup_sql=(
        "CREATE TABLE items (id INT PRIMARY KEY, label TEXT, amount NUMERIC(10, 2));\n"
        "INSERT INTO items VALUES (1, 'uno', 10.50), (2, 'dos', 20.00);"
    ),
    expected_result=((1, "uno", Decimal("10.50")), (2, "dos", Decimal("20.00"))),
    max_seconds=2.0,
)


def _count_sandbox_schemas(engine: Engine) -> int:
    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.schemata "
                "WHERE schema_name LIKE 'sandbox_%'"
            )
        ).scalar_one()
    return int(count)


# --- Lexical validator ------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, label FROM items;",
        "  WITH cte AS (SELECT 1 AS n) SELECT n FROM cte  ",
        "SELECT ';' AS semi, '-- not a comment' AS txt /* block */;",
        "SELECT $$semi;inside;dollar$$ AS s;",
    ],
)
def test_validate_single_select_sql_accepts_valid_queries(sql: str) -> None:
    cleaned = validate_single_select_sql(sql)

    assert not cleaned.endswith(";")


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "x" * (MAX_SQL_LENGTH + 1),
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE public.players;",
        "DROP TABLE items;",
        "ALTER TABLE public.players ADD COLUMN x INT;",
        "DELETE FROM items;",
        "INSERT INTO items VALUES (9, 'hack', 0);",
        "UPDATE items SET label = 'hack';",
        "CREATE TABLE hack (id INT);",
        "SET ROLE tycoon;",
        "RESET ROLE;",
        "COPY items TO PROGRAM 'id';",
        "EXPLAIN SELECT 1;",
        "DO $$ BEGIN PERFORM 1; END $$;",
    ],
)
def test_validate_single_select_sql_blocks_unsafe_or_multi_statements(sql: str) -> None:
    with pytest.raises(ValueError):
        validate_single_select_sql(sql)


# --- Sandbox security / attack suite ----------------------------------------


@pytest.mark.parametrize(
    "attack_sql",
    [
        # Read application tables in public schema
        "SELECT * FROM public.players",
        "SELECT * FROM public.challenges",
        "SELECT * FROM public.attempts",
        "SELECT * FROM public.alembic_version",
        # DDL / DML against public and sandbox tables
        "DROP TABLE public.players",
        "ALTER TABLE public.challenges ADD COLUMN hacked INT",
        "TRUNCATE TABLE public.attempts",
        "DROP TABLE items",
        "ALTER TABLE items ADD COLUMN hacked INT",
        "INSERT INTO items VALUES (3, 'hacked', 0)",
        "UPDATE items SET label = 'hacked'",
        "DELETE FROM items",
        "CREATE TABLE hacked (id INT)",
        "SELECT * INTO hacked FROM items",
        # Multiple statements
        "SELECT 1; SELECT 2;",
        "SELECT 1; DROP TABLE public.players;",
        # Role escalation and session tampering
        "SET ROLE tycoon",
        "RESET ROLE",
        "SELECT set_config('role', 'tycoon', false)",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT set_config('search_path', 'public', false)",
        # Dangerous built-in functions and COPY
        "SELECT pg_read_file('postgresql.conf')",
        "SELECT pg_ls_dir('.')",
        "SELECT pg_terminate_backend(pg_backend_pid())",
        "COPY items TO PROGRAM 'id'",
        # Oversized SQL
        "SELECT " + ("1 + " * 2100) + "1",
    ],
)
def test_sandbox_blocks_attack_and_cleans_schema(
    test_engine: Engine, attack_sql: str
) -> None:
    evaluator = PostgresSandboxEvaluator(test_engine)

    result = evaluator.evaluate(SAFE_CHALLENGE, attack_sql)

    assert isinstance(result, ExecutionFailed)
    assert result.error_message
    assert not re.search(r"sandbox_[0-9a-f]{8,}", result.error_message)
    assert SANDBOX_ROLE not in result.error_message
    assert _count_sandbox_schemas(test_engine) == 0


def test_sandbox_enforces_statement_timeout(test_engine: Engine) -> None:
    fast_timeout = Challenge(
        id=uuid4(),
        code="timeout-probe",
        module="postgresql",
        title="Timeout",
        description="Timeout",
        difficulty=Difficulty.EASY,
        setup_sql="CREATE TABLE t (id INT); INSERT INTO t VALUES (1);",
        expected_result=((1,),),
        max_seconds=0.3,
    )
    evaluator = PostgresSandboxEvaluator(test_engine)

    started = time.perf_counter()
    result = evaluator.evaluate(fast_timeout, "SELECT pg_sleep(5)")
    elapsed = time.perf_counter() - started

    assert isinstance(result, ExecutionFailed)
    assert "tiempo" in result.error_message.lower()
    assert elapsed < 2.5
    assert _count_sandbox_schemas(test_engine) == 0


def test_sandbox_enforces_row_limit_without_hanging(test_engine: Engine) -> None:
    evaluator = PostgresSandboxEvaluator(test_engine)

    result = evaluator.evaluate(
        SAFE_CHALLENGE,
        f"SELECT g FROM generate_series(1, {MAX_RESULT_ROWS + 5000}) AS g",
    )

    assert isinstance(result, ExecutionFailed)
    assert str(MAX_RESULT_ROWS) in result.error_message
    assert _count_sandbox_schemas(test_engine) == 0


def test_sandbox_allows_exactly_max_rows(test_engine: Engine) -> None:
    evaluator = PostgresSandboxEvaluator(test_engine)

    result = evaluator.evaluate(
        SAFE_CHALLENGE,
        f"SELECT g FROM generate_series(1, {MAX_RESULT_ROWS}) AS g",
    )

    assert isinstance(result, ExecutionSucceeded)
    assert len(result.rows) == MAX_RESULT_ROWS
    assert _count_sandbox_schemas(test_engine) == 0


def test_sandbox_cleans_schema_even_on_syntax_or_runtime_error(
    test_engine: Engine,
) -> None:
    evaluator = PostgresSandboxEvaluator(test_engine)

    syntax = evaluator.evaluate(SAFE_CHALLENGE, "SELEC 1 FROM items")
    div_zero = evaluator.evaluate(SAFE_CHALLENGE, "SELECT 1 / 0")

    assert isinstance(syntax, ExecutionFailed)
    assert isinstance(div_zero, ExecutionFailed)
    assert _count_sandbox_schemas(test_engine) == 0


def test_sandbox_raises_evaluator_error_if_setup_fails(test_engine: Engine) -> None:
    broken = Challenge(
        id=uuid4(),
        code="broken-setup",
        module="postgresql",
        title="Broken",
        description="Broken",
        difficulty=Difficulty.EASY,
        setup_sql="CREATE TABLE invalid_syntax (;",
        expected_result=(),
        max_seconds=1.0,
    )
    evaluator = PostgresSandboxEvaluator(test_engine)

    with pytest.raises(EvaluatorError):
        evaluator.evaluate(broken, "SELECT 1")

    assert _count_sandbox_schemas(test_engine) == 0


# --- All 3 MVP challenges (correct and incorrect solutions) -----------------


@pytest.mark.parametrize(
    ("code", "sql", "expected_passed", "expected_message"),
    [
        (
            "dedupe-row-number",
            """
            WITH ranked AS (
                SELECT
                    customer_id,
                    full_name,
                    email,
                    ROW_NUMBER() OVER (
                        PARTITION BY customer_id
                        ORDER BY updated_at DESC
                    ) AS rn
                FROM staging_customers
            )
            SELECT customer_id, full_name, email
            FROM ranked
            WHERE rn = 1
            """,
            True,
            MESSAGE_SOLVED,
        ),
        (
            "dedupe-row-number",
            "SELECT customer_id, full_name, email FROM staging_customers",
            False,
            None,
        ),
        (
            "fix-multiplying-join",
            """
            WITH order_totals AS (
                SELECT customer_id, SUM(total_amount) AS total_ordered
                FROM orders
                GROUP BY customer_id
            ),
            payment_totals AS (
                SELECT o.customer_id, SUM(p.paid_amount) AS total_paid
                FROM orders o
                JOIN payments p ON p.order_id = o.id
                GROUP BY o.customer_id
            )
            SELECT
                c.id,
                c.name,
                ot.total_ordered,
                COALESCE(pt.total_paid, 0.00) AS total_paid
            FROM customers c
            JOIN order_totals ot ON ot.customer_id = c.id
            LEFT JOIN payment_totals pt ON pt.customer_id = c.id
            """,
            True,
            MESSAGE_SOLVED,
        ),
        (
            "fix-multiplying-join",
            """
            SELECT
                c.id,
                c.name,
                SUM(o.total_amount) AS total_ordered,
                SUM(p.paid_amount) AS total_paid
            FROM customers c
            JOIN orders o ON o.customer_id = c.id
            JOIN payments p ON p.order_id = o.id
            GROUP BY c.id, c.name
            """,
            False,
            None,
        ),
        (
            "index-slow-query",
            """
            SELECT id, kind, created_at
            FROM events
            WHERE user_id = 42 AND created_at >= DATE '2026-08-01'
            ORDER BY created_at ASC, id ASC
            """,
            True,
            MESSAGE_SOLVED,
        ),
        (
            "index-slow-query",
            """
            SELECT id, kind, created_at
            FROM events
            WHERE CAST(user_id AS TEXT) = '42' AND created_at >= DATE '2026-08-01'
            ORDER BY created_at ASC, id ASC
            """,
            False,
            MESSAGE_INDEX_NOT_USED,
        ),
    ],
)
def test_mvp_challenges_with_real_sandbox(
    session_factory: object,
    test_engine: Engine,
    code: str,
    sql: str,
    expected_passed: bool,
    expected_message: str | None,
) -> None:
    from sqlalchemy.orm import Session, sessionmaker

    assert isinstance(session_factory, sessionmaker)
    with session_factory() as seed_session:
        assert isinstance(seed_session, Session)
        challenge_repo = SqlAlchemyChallengeRepository(seed_session)
        for ch in MVP_CHALLENGES:
            challenge_repo.upsert(ch)
        seed_session.commit()

    with session_factory() as run_session:
        use_case = SubmitSolution(
            players=SqlAlchemyPlayerRepository(run_session),
            challenges=SqlAlchemyChallengeRepository(run_session),
            attempts=SqlAlchemyAttemptRepository(run_session),
            evaluator=PostgresSandboxEvaluator(test_engine),
            clock=UtcClock(),
            ids=Uuid4Generator(),
            uow=SqlAlchemyUnitOfWork(run_session),
        )
        result = use_case.execute(roblox_user_id=888, code=code, sql=sql)

    assert result.passed is expected_passed
    if expected_message is not None:
        assert result.message == expected_message
    assert _count_sandbox_schemas(test_engine) == 0
