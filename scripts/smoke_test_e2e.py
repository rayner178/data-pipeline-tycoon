"""End-to-end HTTP smoke test simulating Neon NOSUPERUSER roles against live Uvicorn."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql as pg_sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from infrastructure.config import get_database_url  # noqa: E402
from infrastructure.db import resolve_database_url  # noqa: E402
from infrastructure.seed import seed_mvp_challenges  # noqa: E402

SMOKE_DB = "tycoon_e2e_smoke"
OWNER_ROLE = "tycoon_neon_owner"
SANDBOX_ROLE_NAME = "tycoon_neon_sandbox"
SMOKE_PLAYER_ID = 777001

_RESERVED_CONNINFO_KEYS = frozenset(
    {"host", "port", "dbname", "user", "password", "connect_timeout"}
)


def _url_to_conninfo(url: URL, *, dbname: str | None = None) -> str:
    extra_params: dict[str, str] = {}
    for key, raw_value in url.query.items():
        if key in _RESERVED_CONNINFO_KEYS:
            continue
        if isinstance(raw_value, tuple):
            if raw_value:
                extra_params[key] = str(raw_value[-1])
        else:
            extra_params[key] = str(raw_value)
    return psycopg.conninfo.make_conninfo(
        host=url.host or "localhost",
        port=url.port or 5432,
        dbname=dbname or url.database or "postgres",
        user=url.username or "",
        password=url.password or "",
        connect_timeout=5,
        **extra_params,
    )


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _provision_smoke_environment(
    admin_url: URL, owner_pw: str, sandbox_pw: str
) -> tuple[str, str]:
    admin_conninfo = _url_to_conninfo(admin_url, dbname="postgres")
    db_ident = pg_sql.Identifier(SMOKE_DB)
    owner_ident = pg_sql.Identifier(OWNER_ROLE)
    sandbox_ident = pg_sql.Identifier(SANDBOX_ROLE_NAME)

    with psycopg.connect(admin_conninfo, autocommit=True) as conn:
        conn.execute(
            pg_sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(db_ident)
        )
        conn.execute(pg_sql.SQL("DROP ROLE IF EXISTS {}").format(sandbox_ident))
        conn.execute(pg_sql.SQL("DROP ROLE IF EXISTS {}").format(owner_ident))
        conn.execute(
            pg_sql.SQL(
                "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(owner_ident, pg_sql.Literal(owner_pw))
        )
        conn.execute(
            pg_sql.SQL(
                "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sandbox_ident, pg_sql.Literal(sandbox_pw))
        )
        conn.execute(
            pg_sql.SQL("CREATE DATABASE {} OWNER {}").format(db_ident, owner_ident)
        )

    owner_url = admin_url.set(
        username=OWNER_ROLE,
        password=owner_pw,
        database=SMOKE_DB,
    ).render_as_string(hide_password=False)
    sandbox_url = admin_url.set(
        username=SANDBOX_ROLE_NAME,
        password=sandbox_pw,
        database=SMOKE_DB,
    ).render_as_string(hide_password=False)
    return owner_url, sandbox_url


def _cleanup_smoke_environment(admin_url: URL) -> None:
    admin_conninfo = _url_to_conninfo(admin_url, dbname="postgres")
    with psycopg.connect(admin_conninfo, autocommit=True) as conn:
        conn.execute(
            pg_sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                pg_sql.Identifier(SMOKE_DB)
            )
        )
        conn.execute(
            pg_sql.SQL("DROP ROLE IF EXISTS {}").format(
                pg_sql.Identifier(SANDBOX_ROLE_NAME)
            )
        )
        conn.execute(
            pg_sql.SQL("DROP ROLE IF EXISTS {}").format(pg_sql.Identifier(OWNER_ROLE))
        )


def _migrate_and_seed(owner_db_url: str) -> None:
    alembic_cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", owner_db_url)
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(owner_db_url)
    try:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as session:
            seed_mvp_challenges(session)
    finally:
        engine.dispose()


def _wait_for_health(base_url: str, proc: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(
                f"uvicorn exited prematurely (code={proc.returncode}):\n"
                f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )
        try:
            resp = httpx.get(f"{base_url}/health", timeout=1.0)
            if resp.status_code == 200 and resp.json() == {"status": "ok"}:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Timed out waiting for uvicorn /health endpoint")


def _submit_sql(
    client: httpx.Client, headers: dict[str, str], code: str, sql: str
) -> dict[str, Any]:
    resp = client.post(
        f"/challenges/{code}/submit",
        headers=headers,
        json={"roblox_user_id": SMOKE_PLAYER_ID, "sql": sql},
    )
    assert resp.status_code == 200, f"Unexpected HTTP {resp.status_code}: {resp.text}"
    payload: dict[str, Any] = resp.json()
    return payload


def _run_http_checks(base_url: str, api_key: str, owner_db_url: str) -> None:
    auth_headers = {"X-API-Key": api_key}
    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        # 1. Public healthcheck
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        print("[PASS] 1. GET /health -> 200 ok")

        # 2. Auth + challenges list
        no_key = client.get("/challenges")
        bad_key = client.get("/challenges", headers={"X-API-Key": "wrong-key"})
        ok_challenges = client.get("/challenges", headers=auth_headers)
        assert no_key.status_code == 401
        assert bad_key.status_code == 403
        assert ok_challenges.status_code == 200
        challenges = ok_challenges.json()
        assert [c["code"] for c in challenges] == [
            "dedupe-row-number",
            "fix-multiplying-join",
            "index-slow-query",
        ]
        for ch in challenges:
            assert "setup_sql" not in ch
            assert "expected_result" not in ch
        print("[PASS] 2. GET /challenges auth (401/403/200) & 3 MVP challenges")

        # 3. All 3 challenges: incorrect diagnostics + correct solutions
        c1_wrong = _submit_sql(
            client,
            auth_headers,
            "dedupe-row-number",
            "SELECT customer_id, full_name, email FROM staging_customers",
        )
        assert c1_wrong["passed"] is False
        assert c1_wrong["columns"] == ["customer_id", "full_name", "email"]
        assert len(c1_wrong["preview_rows"]) == 5
        assert "se esperaban 3" in c1_wrong["message"].lower()

        c1_ok = _submit_sql(
            client,
            auth_headers,
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
        )
        assert c1_ok["passed"] is True
        assert isinstance(c1_ok["execution_ms"], int) and c1_ok["execution_ms"] >= 0
        assert len(c1_ok["preview_rows"]) == 3

        c2_wrong = _submit_sql(
            client,
            auth_headers,
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
        )
        assert c2_wrong["passed"] is False
        assert len(c2_wrong["preview_rows"]) == 2
        assert "valores no coinciden" in c2_wrong["message"].lower()
        assert "150.00" not in c2_wrong["message"]

        c2_ok = _submit_sql(
            client,
            auth_headers,
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
        )
        assert c2_ok["passed"] is True
        assert len(c2_ok["preview_rows"]) == 2

        c3_wrong = _submit_sql(
            client,
            auth_headers,
            "index-slow-query",
            """
            SELECT id, kind, created_at
            FROM events
            WHERE CAST(user_id AS TEXT) = '42' AND created_at >= DATE '2026-08-01'
            ORDER BY created_at ASC, id ASC
            """,
        )
        assert c3_wrong["passed"] is False
        assert "índice" in c3_wrong["message"].lower()
        assert len(c3_wrong["preview_rows"]) == 8

        c3_ok = _submit_sql(
            client,
            auth_headers,
            "index-slow-query",
            """
            SELECT id, kind, created_at
            FROM events
            WHERE user_id = 42 AND created_at >= DATE '2026-08-01'
            ORDER BY created_at ASC, id ASC
            """,
        )
        assert c3_ok["passed"] is True
        assert c3_ok["columns"] == ["id", "kind", "created_at"]
        assert len(c3_ok["preview_rows"]) == 8
        print("[PASS] 3. All 3 challenges failed/passed with preview_rows & EXPLAIN")

        # 4. Player progress
        progress_resp = client.get(
            f"/players/{SMOKE_PLAYER_ID}/progress", headers=auth_headers
        )
        assert progress_resp.status_code == 200
        progress = progress_resp.json()
        assert progress["roblox_user_id"] == SMOKE_PLAYER_ID
        completed_codes = {item["code"] for item in progress["completed"]}
        assert completed_codes == {
            "dedupe-row-number",
            "fix-multiplying-join",
            "index-slow-query",
        }
        assert all(
            isinstance(item["best_ms"], int) and item["best_ms"] >= 0
            for item in progress["completed"]
        )
        print("[PASS] 4. GET /players/{id}/progress tracks 3 solved challenges")

        # 5. Live security attacks
        attacks = (
            "SELECT * FROM public.players",
            "SELECT pg_catalog.\"set_config\"('role', 'tycoon_neon_owner', false)",
            "SELECT 1; DROP TABLE public.players;",
        )
        for attack_sql in attacks:
            attack_res = _submit_sql(
                client, auth_headers, "dedupe-row-number", attack_sql
            )
            assert attack_res["passed"] is False
            assert OWNER_ROLE not in attack_res["message"]
            assert SANDBOX_ROLE_NAME not in attack_res["message"]
            assert "sandbox_" not in attack_res["message"]
        print(
            "[PASS] 5. Live HTTP SQL attacks blocked cleanly without role/schema leaks"
        )

    # 6. Verify no leftover sandbox schemas
    check_engine = create_engine(owner_db_url)
    try:
        with check_engine.connect() as conn:
            leftover = conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.schemata "
                    "WHERE schema_name LIKE 'sandbox_%'"
                )
            ).scalar_one()
            assert int(leftover) == 0, f"Found {leftover} leftover sandbox schemas!"
    finally:
        check_engine.dispose()
    print("[PASS] 6. Zero leftover sandbox_* schemas verified in PostgreSQL")


def main() -> int:
    admin_url = make_url(resolve_database_url(get_database_url()))
    owner_pw = secrets.token_urlsafe(18)
    sandbox_pw = secrets.token_urlsafe(18)
    smoke_api_key = secrets.token_urlsafe(24)

    proc: subprocess.Popen[str] | None = None
    try:
        owner_db_url, sandbox_db_url = _provision_smoke_environment(
            admin_url, owner_pw, sandbox_pw
        )
        _migrate_and_seed(owner_db_url)

        port = _pick_free_port()
        proc_env = os.environ.copy()
        proc_env["DATABASE_URL"] = owner_db_url
        proc_env["SANDBOX_DATABASE_URL"] = sandbox_db_url
        proc_env["API_KEY"] = smoke_api_key
        proc_env["PYTHONPATH"] = str(_SRC_DIR)
        proc_env.pop("TEST_DATABASE_URL", None)

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(_REPO_ROOT),
            env=proc_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url, proc)
        _run_http_checks(base_url, smoke_api_key, owner_db_url)
        print("[OK] Neon NOSUPERUSER E2E smoke test succeeded.")
        return 0
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
        _cleanup_smoke_environment(admin_url)


if __name__ == "__main__":
    raise SystemExit(main())
