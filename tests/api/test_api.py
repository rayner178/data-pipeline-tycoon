"""Tests for the FastAPI layer, X-API-Key authentication, schemas and OpenAPI."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from api.dependencies import (
    get_configured_api_key,
    get_db_session,
    get_list_challenges_use_case,
    get_progress_use_case,
    get_solution_evaluator,
    get_submit_solution_use_case,
)
from api.schemas import MAX_SQL_LENGTH
from application.errors import EvaluatorError
from application.evaluation import ExecutionFailed, ExecutionSucceeded
from application.use_cases.get_progress import GetProgress
from application.use_cases.list_challenges import ListChallenges
from application.use_cases.submit_solution import SubmitSolution
from domain.entities import Challenge, Difficulty
from infrastructure.config import (
    derive_test_database_url,
    get_api_key,
    get_database_url,
)
from infrastructure.db import create_db_engine, resolve_database_url
from infrastructure.sandbox import PostgresSandboxEvaluator
from infrastructure.seed import seed_mvp_challenges
from tests.application.fakes import (
    FakeEvaluator,
    FakeUnitOfWork,
    FixedClock,
    InMemoryAttemptRepository,
    InMemoryChallengeRepository,
    InMemoryPlayerRepository,
    SequentialIdGenerator,
)
from tests.domain.factories import NOW, make_challenge

TEST_API_KEY = "test-secret-key-for-roblox"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}
REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_challenges() -> list[Challenge]:
    return [
        make_challenge(
            id=uuid4(),
            code="join-fix",
            title="Corregir JOIN",
            difficulty=Difficulty.MEDIUM,
            expected_result=((1,),),
        ),
        make_challenge(
            id=uuid4(),
            code="dedupe-row-number",
            title="Eliminar duplicados",
            difficulty=Difficulty.EASY,
            expected_result=((1, "Ana"),),
        ),
    ]


class _ApiTestEnv:
    def __init__(self, evaluator: FakeEvaluator | None = None) -> None:
        self.players = InMemoryPlayerRepository()
        self.challenges = InMemoryChallengeRepository(_make_challenges())
        self.attempts = InMemoryAttemptRepository()
        self.evaluator = evaluator or FakeEvaluator(
            ExecutionSucceeded(rows=((1, "Ana"),), execution_ms=14)
        )
        self.clock = FixedClock(NOW)
        self.ids = SequentialIdGenerator()
        self.uow = FakeUnitOfWork()
        self.app = create_app()
        self.app.dependency_overrides[get_configured_api_key] = lambda: TEST_API_KEY
        self.app.dependency_overrides[get_list_challenges_use_case] = lambda: (
            ListChallenges(self.challenges)
        )
        self.app.dependency_overrides[get_submit_solution_use_case] = lambda: (
            SubmitSolution(
                players=self.players,
                challenges=self.challenges,
                attempts=self.attempts,
                evaluator=self.evaluator,
                clock=self.clock,
                ids=self.ids,
                uow=self.uow,
            )
        )
        self.app.dependency_overrides[get_progress_use_case] = lambda: GetProgress(
            players=self.players,
            challenges=self.challenges,
            attempts=self.attempts,
        )
        self.client = TestClient(self.app)


# --- Config: API_KEY --------------------------------------------------------


def test_get_api_key_reads_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("API_KEY", "super-secret")

    assert get_api_key(env_file=tmp_path / ".env") == "super-secret"


def test_get_api_key_falls_back_to_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=from-dotenv\n", encoding="utf-8")

    assert get_api_key(env_file=env_file) == "from-dotenv"


def test_get_api_key_raises_when_missing_or_blank(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("API_KEY", "   ")

    with pytest.raises(RuntimeError, match="API_KEY"):
        get_api_key(env_file=tmp_path / ".env")


# --- Health -----------------------------------------------------------------


def test_health_is_public_and_returns_ok() -> None:
    env = _ApiTestEnv()

    response = env.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Authentication ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/challenges", None),
        (
            "POST",
            "/challenges/dedupe-row-number/submit",
            {"roblox_user_id": 10, "sql": "SELECT 1;"},
        ),
        ("GET", "/players/10/progress", None),
    ],
)
def test_protected_endpoints_reject_missing_or_empty_api_key(
    method: str, path: str, payload: dict[str, object] | None
) -> None:
    env = _ApiTestEnv()

    missing = env.client.request(method, path, json=payload)
    empty = env.client.request(method, path, json=payload, headers={"X-API-Key": ""})

    assert missing.status_code == 401
    assert empty.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/challenges", None),
        (
            "POST",
            "/challenges/dedupe-row-number/submit",
            {"roblox_user_id": 10, "sql": "SELECT 1;"},
        ),
        ("GET", "/players/10/progress", None),
    ],
)
def test_protected_endpoints_reject_wrong_api_key(
    method: str, path: str, payload: dict[str, object] | None
) -> None:
    env = _ApiTestEnv()

    response = env.client.request(
        method, path, json=payload, headers={"X-API-Key": "wrong-key"}
    )

    assert response.status_code == 403


# --- GET /challenges --------------------------------------------------------


def test_list_challenges_returns_ordered_public_summaries() -> None:
    env = _ApiTestEnv()

    response = env.client.get("/challenges", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert [item["code"] for item in body] == ["dedupe-row-number", "join-fix"]
    for item in body:
        assert set(item) == {"code", "module", "title", "description", "difficulty"}
        assert "setup_sql" not in item
        assert "expected_result" not in item


# --- POST /challenges/{code}/submit -----------------------------------------


def test_submit_correct_solution_returns_passed() -> None:
    env = _ApiTestEnv()

    response = env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELECT 1, 'Ana';"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "passed": True,
        "execution_ms": 14,
        "message": "¡Reto superado!",
    }
    assert env.uow.committed == 1


def test_submit_wrong_solution_returns_failed() -> None:
    env = _ApiTestEnv(
        FakeEvaluator(ExecutionSucceeded(rows=((99, "Otro"),), execution_ms=8))
    )

    response = env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELECT 99, 'Otro';"},
    )

    assert response.status_code == 200
    assert response.json()["passed"] is False
    assert response.json()["execution_ms"] == 8


def test_submit_player_sql_error_returns_failed_with_message() -> None:
    env = _ApiTestEnv(
        FakeEvaluator(
            ExecutionFailed(error_message="Error de sintaxis SQL", execution_ms=None)
        )
    )

    response = env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELEC 1;"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "passed": False,
        "execution_ms": None,
        "message": "Error de sintaxis SQL",
    }


def test_submit_unknown_challenge_returns_404_without_internal_details() -> None:
    env = _ApiTestEnv()

    response = env.client.post(
        "/challenges/non-existent/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELECT 1;"},
    )

    assert response.status_code == 404
    assert "Traceback" not in response.text


@pytest.mark.parametrize("sql", ["", "   \n\t ", "x" * (MAX_SQL_LENGTH + 1)])
def test_submit_rejects_empty_or_oversized_sql_with_422(sql: str) -> None:
    env = _ApiTestEnv()

    response = env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": sql},
    )

    assert response.status_code == 422
    assert env.evaluator.calls == []


@pytest.mark.parametrize("roblox_user_id", [0, -5])
def test_submit_rejects_non_positive_roblox_user_id(roblox_user_id: int) -> None:
    env = _ApiTestEnv()

    response = env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": roblox_user_id, "sql": "SELECT 1;"},
    )

    assert response.status_code == 422


def test_submit_rejects_extra_fields() -> None:
    env = _ApiTestEnv()

    response = env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELECT 1;", "unexpected": True},
    )

    assert response.status_code == 422


def test_submit_evaluator_outage_returns_503_and_hides_internal_details() -> None:
    secret_cause = "FATAL: password auth failed for secret-db-host-10.0.0.99"
    env = _ApiTestEnv(FakeEvaluator(error=EvaluatorError(secret_cause)))

    response = env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELECT 1;"},
    )

    assert response.status_code == 503
    assert "secret-db-host-10.0.0.99" not in response.text
    assert "password" not in response.text
    assert env.attempts.attempts == []


# --- GET /players/{roblox_user_id}/progress ---------------------------------


def test_progress_for_new_player_is_empty() -> None:
    env = _ApiTestEnv()

    response = env.client.get("/players/999/progress", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"roblox_user_id": 999, "completed": []}


def test_progress_returns_completed_challenges_and_best_time() -> None:
    env = _ApiTestEnv(
        FakeEvaluator(ExecutionSucceeded(rows=((1, "Ana"),), execution_ms=25))
    )
    env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELECT 1, 'Ana';"},
    )
    env.clock.current = NOW + timedelta(minutes=2)
    env.evaluator = FakeEvaluator(
        ExecutionSucceeded(rows=((1, "Ana"),), execution_ms=11)
    )
    env.client.post(
        "/challenges/dedupe-row-number/submit",
        headers=AUTH_HEADERS,
        json={"roblox_user_id": 42, "sql": "SELECT 1, 'Ana';"},
    )

    response = env.client.get("/players/42/progress", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["roblox_user_id"] == 42
    assert len(body["completed"]) == 1
    assert body["completed"][0]["code"] == "dedupe-row-number"
    assert body["completed"][0]["best_ms"] == 11


@pytest.mark.parametrize("roblox_user_id", [0, -1])
def test_progress_rejects_non_positive_roblox_user_id(roblox_user_id: int) -> None:
    env = _ApiTestEnv()

    response = env.client.get(
        f"/players/{roblox_user_id}/progress", headers=AUTH_HEADERS
    )

    assert response.status_code == 422


# --- OpenAPI & Docs ---------------------------------------------------------


def test_openapi_matches_spec_contract_and_docs_load() -> None:
    client = TestClient(create_app())

    docs = client.get("/docs")
    schema = client.get("/openapi.json")

    assert docs.status_code == 200
    assert schema.status_code == 200
    openapi = schema.json()
    assert {
        "/health",
        "/challenges",
        "/challenges/{code}/submit",
        "/players/{roblox_user_id}/progress",
    }.issubset(openapi["paths"])
    security_schemes = openapi["components"]["securitySchemes"]
    assert any(
        scheme.get("in") == "header" and scheme.get("name") == "X-API-Key"
        for scheme in security_schemes.values()
    )


# --- Integration with PostgreSQL test DB ------------------------------------


@contextmanager
def _seeded_test_db() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    test_url = resolve_database_url(derive_test_database_url(get_database_url()))
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", test_url)
    command.upgrade(alembic_cfg, "head")

    engine = create_db_engine(test_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM attempts"))
            conn.execute(text("DELETE FROM players"))
            conn.execute(text("DELETE FROM challenges"))

        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as seed_session:
            seed_mvp_challenges(seed_session)
        yield engine, factory
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM attempts"))
            conn.execute(text("DELETE FROM players"))
            conn.execute(text("DELETE FROM challenges"))
        engine.dispose()


def test_api_end_to_end_with_postgres_repositories() -> None:
    with _seeded_test_db() as (_engine, factory):

        def override_session() -> Iterator[Session]:
            with factory() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_configured_api_key] = lambda: TEST_API_KEY
        app.dependency_overrides[get_db_session] = override_session
        app.dependency_overrides[get_solution_evaluator] = lambda: FakeEvaluator(
            ExecutionSucceeded(
                rows=(
                    (1, "Ana Pérez", "ana@example.com"),
                    (2, "Luis Gómez", "luis@example.com"),
                    (3, "Marta Díaz", None),
                ),
                execution_ms=19,
            )
        )
        client = TestClient(app)

        listed = client.get("/challenges", headers=AUTH_HEADERS)
        assert listed.status_code == 200
        assert [c["code"] for c in listed.json()] == [
            "dedupe-row-number",
            "fix-multiplying-join",
            "index-slow-query",
        ]

        submitted = client.post(
            "/challenges/dedupe-row-number/submit",
            headers=AUTH_HEADERS,
            json={"roblox_user_id": 777, "sql": "SELECT 1, 'Ana';"},
        )
        assert submitted.status_code == 200
        assert submitted.json()["passed"] is True

        progress = client.get("/players/777/progress", headers=AUTH_HEADERS)
        assert progress.status_code == 200
        assert len(progress.json()["completed"]) == 1
        assert progress.json()["completed"][0]["code"] == "dedupe-row-number"
        assert progress.json()["completed"][0]["best_ms"] == 19


def test_api_end_to_end_with_real_sql_sandbox() -> None:
    with _seeded_test_db() as (engine, factory):

        def override_session() -> Iterator[Session]:
            with factory() as session:
                yield session

        evaluator = PostgresSandboxEvaluator(engine)
        app = create_app()
        app.dependency_overrides[get_configured_api_key] = lambda: TEST_API_KEY
        app.dependency_overrides[get_db_session] = override_session
        app.dependency_overrides[get_solution_evaluator] = lambda: evaluator
        client = TestClient(app)

        attack = client.post(
            "/challenges/dedupe-row-number/submit",
            headers=AUTH_HEADERS,
            json={"roblox_user_id": 888, "sql": "SELECT * FROM public.players"},
        )
        assert attack.status_code == 200
        assert attack.json()["passed"] is False

        solved = client.post(
            "/challenges/dedupe-row-number/submit",
            headers=AUTH_HEADERS,
            json={
                "roblox_user_id": 888,
                "sql": (
                    "WITH ranked AS ("
                    "SELECT customer_id, full_name, email, "
                    "ROW_NUMBER() OVER ("
                    "PARTITION BY customer_id ORDER BY updated_at DESC"
                    ") AS rn FROM staging_customers"
                    ") SELECT customer_id, full_name, email FROM ranked WHERE rn = 1"
                ),
            },
        )
        assert solved.status_code == 200
        assert solved.json()["passed"] is True
        assert solved.json()["execution_ms"] is not None

        progress = client.get("/players/888/progress", headers=AUTH_HEADERS)
        assert progress.status_code == 200
        assert len(progress.json()["completed"]) == 1
        assert progress.json()["completed"][0]["code"] == "dedupe-row-number"
