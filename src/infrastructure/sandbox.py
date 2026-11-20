"""Isolated, least-privilege PostgreSQL SQL sandbox evaluator (SPEC section 7)."""

import logging
import re
import secrets
import time
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql as pg_sql
from psycopg.errors import (
    InsufficientPrivilege,
    QueryCanceled,
    UndefinedFunction,
)
from sqlalchemy import Engine
from sqlalchemy.engine import URL, make_url

from application.errors import EvaluatorError
from application.evaluation import EvaluationResult, ExecutionFailed, ExecutionSucceeded
from application.ports import SolutionEvaluator
from domain.entities import Challenge
from domain.result_matching import Cell, FrozenResult
from infrastructure.config import _normalize_psycopg_scheme

logger = logging.getLogger(__name__)

MAX_SQL_LENGTH = 8_000
MAX_RESULT_ROWS = 1_000
SANDBOX_ROLE = "tycoon_sandbox_player"

_ALLOWED_START_KEYWORDS = frozenset({"SELECT", "WITH"})
_FIRST_WORD_RE = re.compile(r"^\s*\(*\s*([A-Za-z_][A-Za-z0-9_]*)")
_DOLLAR_TAG_RE = re.compile(r"^\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_FORBIDDEN_FUNCTION_RE = re.compile(r"\bset_config\s*\(", re.IGNORECASE)
_SANDBOX_SCHEMA_RE = re.compile(r"sandbox_[0-9a-f]{32}")
_INTERNAL_NAMES_RE = re.compile(r"\b(?:tycoon_sandbox_player|tycoon)\b")
_RESERVED_CONNINFO_KEYS = frozenset(
    {"host", "port", "dbname", "user", "password", "connect_timeout"}
)

_DANGEROUS_FUNCTIONS = (
    "pg_catalog.set_config(text, text, boolean)",
    "pg_catalog.pg_terminate_backend(integer)",
    "pg_catalog.pg_cancel_backend(integer)",
    "pg_catalog.pg_reload_conf()",
    "pg_catalog.pg_read_file(text)",
    "pg_catalog.pg_read_file(text, bigint, bigint)",
    "pg_catalog.pg_read_file(text, bigint, bigint, boolean)",
    "pg_catalog.pg_read_binary_file(text)",
    "pg_catalog.pg_read_binary_file(text, bigint, bigint)",
    "pg_catalog.pg_read_binary_file(text, bigint, bigint, boolean)",
    "pg_catalog.pg_ls_dir(text)",
    "pg_catalog.pg_ls_dir(text, boolean, boolean)",
    "pg_catalog.pg_stat_file(text)",
    "pg_catalog.pg_stat_file(text, boolean)",
)


def validate_single_select_sql(
    raw_sql: str, *, max_length: int = MAX_SQL_LENGTH
) -> str:
    """Validate SQL length, single-statement discipline and read-only SELECT/WITH."""
    if len(raw_sql) > max_length:
        raise ValueError(
            f"La consulta SQL excede el límite de {max_length} caracteres."
        )
    stripped_code, semicolon_positions = _scan_sql(raw_sql)
    if not stripped_code.strip():
        raise ValueError("La consulta SQL está vacía.")
    if semicolon_positions:
        first_semi = semicolon_positions[0]
        if len(semicolon_positions) > 1 or stripped_code[first_semi + 1 :].strip():
            raise ValueError("Solo se permite una sentencia SQL por envío.")
        cleaned = _strip_trailing_semicolon(raw_sql)
    else:
        cleaned = raw_sql.strip()

    match = _FIRST_WORD_RE.match(stripped_code)
    if not match or match.group(1).upper() not in _ALLOWED_START_KEYWORDS:
        raise ValueError("Solo se permiten consultas de lectura (SELECT o WITH).")
    if _FORBIDDEN_FUNCTION_RE.search(stripped_code):
        raise ValueError("No se permite invocar la función set_config.")
    return cleaned


class PostgresSandboxEvaluator(SolutionEvaluator):
    """Execute player SQL inside a disposable schema with a least-privilege role."""

    def __init__(
        self,
        admin_engine: Engine,
        *,
        sandbox_database_url: str | None = None,
        max_rows: int = MAX_RESULT_ROWS,
        max_sql_length: int = MAX_SQL_LENGTH,
    ) -> None:
        self._admin_engine = admin_engine
        self._max_rows = max_rows
        self._max_sql_length = max_sql_length
        self._sandbox_password = secrets.token_urlsafe(32)
        self._provisioned = False
        self._sandbox_url: URL | None = None
        self._sandbox_role: str = SANDBOX_ROLE

        if sandbox_database_url is not None and sandbox_database_url.strip():
            parsed_sandbox = make_url(
                _normalize_psycopg_scheme(sandbox_database_url.strip())
            )
            sandbox_user = parsed_sandbox.username
            if not sandbox_user:
                raise EvaluatorError(
                    "SANDBOX_DATABASE_URL must specify a database username"
                )
            if (
                self._admin_engine.url.username
                and sandbox_user == self._admin_engine.url.username
            ):
                raise EvaluatorError(
                    "SANDBOX_DATABASE_URL must use a least-privilege role "
                    "separate from DATABASE_URL"
                )
            self._sandbox_url = parsed_sandbox
            self._sandbox_role = sandbox_user

    def evaluate(self, challenge: Challenge, sql: str) -> EvaluationResult:
        try:
            cleaned_sql = validate_single_select_sql(
                sql, max_length=self._max_sql_length
            )
        except ValueError as exc:
            return ExecutionFailed(error_message=str(exc), execution_ms=None)

        self._ensure_provisioned()
        schema_name = f"sandbox_{uuid4().hex}"
        try:
            self._prepare_schema(schema_name, challenge.setup_sql)
            return self._run_in_sandbox(schema_name, challenge, cleaned_sql)
        finally:
            self._drop_schema(schema_name)

    def _admin_conninfo(self) -> str:
        return self._make_conninfo(
            user=self._admin_engine.url.username or "",
            password=self._admin_engine.url.password or "",
        )

    def _sandbox_conninfo(self) -> str:
        if self._sandbox_url is not None:
            return self._make_conninfo(
                user=self._sandbox_url.username or "",
                password=self._sandbox_url.password or "",
                base_url=self._sandbox_url,
            )
        return self._make_conninfo(
            user=self._sandbox_role,
            password=self._sandbox_password,
        )

    def _make_conninfo(
        self, *, user: str, password: str, base_url: URL | None = None
    ) -> str:
        url = base_url if base_url is not None else self._admin_engine.url
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
            dbname=url.database or "postgres",
            user=user,
            password=password,
            connect_timeout=5,
            **extra_params,
        )

    def _ensure_provisioned(self) -> None:
        if self._provisioned:
            return
        try:
            with psycopg.connect(self._admin_conninfo(), autocommit=True) as conn:
                self._provision_role_and_locks(conn)
                self._verify_sandbox_role_isolation(conn)
        except EvaluatorError:
            raise
        except psycopg.Error as exc:
            raise EvaluatorError("Failed to provision PostgreSQL sandbox role") from exc
        self._provisioned = True

    def _provision_role_and_locks(self, conn: psycopg.Connection[Any]) -> None:
        db_name = self._admin_engine.url.database or "postgres"
        role_ident = pg_sql.Identifier(self._sandbox_role)
        db_ident = pg_sql.Identifier(db_name)

        role_exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s",
            (self._sandbox_role,),
        ).fetchone()
        if self._sandbox_url is None:
            password_lit = pg_sql.Literal(self._sandbox_password)
            if role_exists is None:
                conn.execute(
                    pg_sql.SQL(
                        "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(role_ident, password_lit)
                )
            else:
                conn.execute(
                    pg_sql.SQL(
                        "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(role_ident, password_lit)
                )
        elif role_exists is None:
            raise EvaluatorError(
                f"Configured sandbox role {self._sandbox_role!r} "
                "does not exist in PostgreSQL"
            )

        for stmt in (
            pg_sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC, {}").format(
                role_ident
            ),
            pg_sql.SQL(
                "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, {}"
            ).format(role_ident),
            pg_sql.SQL(
                "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, {}"
            ).format(role_ident),
            pg_sql.SQL(
                "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, {}"
            ).format(role_ident),
            pg_sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "REVOKE ALL ON TABLES FROM PUBLIC, {}"
            ).format(role_ident),
            pg_sql.SQL(
                "REVOKE CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC, {}"
            ).format(db_ident, role_ident),
        ):
            try:
                conn.execute(stmt)
            except InsufficientPrivilege:
                continue

        if self._sandbox_url is None:
            conn.execute(
                pg_sql.SQL("ALTER ROLE {} SET work_mem = '4MB'").format(role_ident)
            )
            try:
                conn.execute(
                    pg_sql.SQL("ALTER ROLE {} SET temp_file_limit = '10MB'").format(
                        role_ident
                    )
                )
            except InsufficientPrivilege:
                pass

        quoted_role = role_ident.as_string()
        for fn_signature in _DANGEROUS_FUNCTIONS:
            try:
                conn.execute(
                    f"REVOKE EXECUTE ON FUNCTION {fn_signature} "
                    f"FROM PUBLIC, {quoted_role}"
                )
            except (UndefinedFunction, InsufficientPrivilege):
                continue

    def _verify_sandbox_role_isolation(self, conn: psycopg.Connection[Any]) -> None:
        row = conn.execute(
            """
            SELECT
                r.rolsuper,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'pg_read_all_data'
                    )
                    THEN pg_has_role(r.oid, 'pg_read_all_data', 'MEMBER')
                    ELSE FALSE
                END,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'pg_write_all_data'
                    )
                    THEN pg_has_role(r.oid, 'pg_write_all_data', 'MEMBER')
                    ELSE FALSE
                END,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'neon_superuser'
                    )
                    THEN pg_has_role(r.oid, 'neon_superuser', 'MEMBER')
                    ELSE FALSE
                END,
                CASE
                    WHEN to_regclass('public.players') IS NOT NULL
                    THEN has_table_privilege(r.oid, 'public.players', 'SELECT')
                    ELSE FALSE
                END,
                CASE
                    WHEN to_regclass('public.challenges') IS NOT NULL
                    THEN has_table_privilege(r.oid, 'public.challenges', 'SELECT')
                    ELSE FALSE
                END,
                CASE
                    WHEN to_regclass('public.attempts') IS NOT NULL
                    THEN has_table_privilege(r.oid, 'public.attempts', 'SELECT')
                    ELSE FALSE
                END
            FROM pg_roles r
            WHERE r.rolname = %s
            """,
            (self._sandbox_role,),
        ).fetchone()
        if row is None:
            raise EvaluatorError(
                f"Sandbox role {self._sandbox_role!r} does not exist in pg_roles"
            )
        (
            is_super,
            can_read_all,
            can_write_all,
            is_neon_super,
            can_read_players,
            can_read_challenges,
            can_read_attempts,
        ) = (bool(v) for v in row)
        violations: list[str] = []
        if is_super:
            violations.append("rolsuper=true")
        if can_read_all:
            violations.append("pg_read_all_data")
        if can_write_all:
            violations.append("pg_write_all_data")
        if is_neon_super:
            violations.append("neon_superuser")
        if can_read_players:
            violations.append("SELECT on public.players")
        if can_read_challenges:
            violations.append("SELECT on public.challenges")
        if can_read_attempts:
            violations.append("SELECT on public.attempts")
        if violations:
            details = ", ".join(violations)
            logger.error(
                "Refusing to run SQL sandbox with over-privileged role %r: %s",
                self._sandbox_role,
                details,
            )
            raise EvaluatorError(
                f"Sandbox role {self._sandbox_role!r} is over-privileged ({details})"
            )

    def _prepare_schema(self, schema_name: str, setup_sql: str) -> None:
        schema_ident = pg_sql.Identifier(schema_name)
        role_ident = pg_sql.Identifier(self._sandbox_role)
        try:
            with psycopg.connect(self._admin_conninfo(), autocommit=False) as conn:
                with conn.transaction():
                    conn.execute(pg_sql.SQL("CREATE SCHEMA {}").format(schema_ident))
                    conn.execute(
                        pg_sql.SQL("SET LOCAL search_path = {}, pg_catalog").format(
                            schema_ident
                        )
                    )
                    conn.execute(setup_sql)
                    conn.execute(
                        pg_sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                            schema_ident, role_ident
                        )
                    )
                    conn.execute(
                        pg_sql.SQL(
                            "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}"
                        ).format(schema_ident, role_ident)
                    )
        except psycopg.Error as exc:
            raise EvaluatorError("Failed to initialize challenge schema") from exc

    def _drop_schema(self, schema_name: str) -> None:
        try:
            with psycopg.connect(self._admin_conninfo(), autocommit=True) as conn:
                conn.execute(
                    pg_sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        pg_sql.Identifier(schema_name)
                    )
                )
        except psycopg.Error as exc:
            raise EvaluatorError("Failed to clean up sandbox schema") from exc

    def _run_in_sandbox(
        self, schema_name: str, challenge: Challenge, cleaned_sql: str
    ) -> EvaluationResult:
        try:
            conn = psycopg.connect(self._sandbox_conninfo(), autocommit=False)
        except psycopg.Error as exc:
            raise EvaluatorError("Failed to connect as sandbox role") from exc

        timeout_ms = max(100, int(challenge.max_seconds * 1000))
        started = time.perf_counter()
        try:
            with conn:
                with conn.transaction(force_rollback=True):
                    conn.execute(
                        pg_sql.SQL("SET LOCAL statement_timeout = {}").format(
                            pg_sql.Literal(f"{timeout_ms}ms")
                        )
                    )
                    conn.execute("SET LOCAL lock_timeout = '500ms'")
                    conn.execute("SET LOCAL work_mem = '4MB'")
                    conn.execute(
                        pg_sql.SQL("SET LOCAL search_path = {}, pg_catalog").format(
                            pg_sql.Identifier(schema_name)
                        )
                    )
                    plan_text: str | None = None
                    if challenge.requires_index_plan():
                        explain_rows = conn.execute(
                            f"EXPLAIN (COSTS OFF) {cleaned_sql}"
                        ).fetchall()
                        plan_text = "\n".join(str(row[0]) for row in explain_rows)
                    started = time.perf_counter()
                    with conn.cursor(name="sandbox_cur") as cur:
                        cur.execute(cleaned_sql)
                        raw_rows = cur.fetchmany(self._max_rows + 1)
                        columns = (
                            tuple(col.name for col in cur.description)
                            if cur.description is not None
                            else ()
                        )
                    elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
                    if len(raw_rows) > self._max_rows:
                        return ExecutionFailed(
                            error_message=(
                                f"La consulta superó el límite máximo de "
                                f"{self._max_rows} filas."
                            ),
                            execution_ms=elapsed_ms,
                        )
                    rows = _freeze_rows(raw_rows)
                    return ExecutionSucceeded(
                        rows=rows,
                        execution_ms=elapsed_ms,
                        columns=columns,
                        plan=plan_text,
                    )
        except QueryCanceled:
            elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
            return ExecutionFailed(
                error_message="La consulta excedió el tiempo máximo permitido.",
                execution_ms=elapsed_ms,
            )
        except InsufficientPrivilege:
            return ExecutionFailed(
                error_message=(
                    "Permiso denegado: solo puedes consultar las tablas del reto."
                ),
                execution_ms=None,
            )
        except psycopg.Error as exc:
            extra_names = tuple(
                name
                for name in (
                    self._sandbox_role,
                    self._admin_engine.url.username or "",
                )
                if name
            )
            return ExecutionFailed(
                error_message=_sanitize_pg_error(exc, extra_names=extra_names),
                execution_ms=None,
            )


def _freeze_rows(raw_rows: list[tuple[Any, ...]]) -> FrozenResult:
    return tuple(tuple(_convert_cell(cell) for cell in row) for row in raw_rows)


def _convert_cell(value: object) -> Cell:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float | Decimal | str):
        return value
    if isinstance(value, datetime | date | dt_time | UUID):
        return str(value)
    return str(value)


def _sanitize_pg_error(exc: psycopg.Error, extra_names: tuple[str, ...] = ()) -> str:
    primary = exc.diag.message_primary if exc.diag is not None else None
    raw = primary or str(exc).splitlines()[0]
    cleaned = _SANDBOX_SCHEMA_RE.sub("sandbox", raw)
    cleaned = _INTERNAL_NAMES_RE.sub("sandbox_user", cleaned)
    for name in extra_names:
        cleaned = re.sub(rf"\b{re.escape(name)}\b", "sandbox_user", cleaned)
    return cleaned.strip() or "Error al ejecutar la consulta SQL."


def _strip_trailing_semicolon(raw_sql: str) -> str:
    _, semis = _scan_sql(raw_sql)
    if not semis:
        return raw_sql.strip()
    return raw_sql[: semis[0]].strip()


def _scan_sql(raw_sql: str) -> tuple[str, list[int]]:
    """Return SQL with comments/literals blanked out and outer semicolon positions."""
    out: list[str] = []
    semicolons: list[int] = []
    n = len(raw_sql)
    i = 0

    while i < n:
        ch = raw_sql[i]
        nxt = raw_sql[i + 1] if i + 1 < n else ""

        # Line comment -- ... \n
        if ch == "-" and nxt == "-":
            while i < n and raw_sql[i] != "\n":
                out.append(" ")
                i += 1
            continue

        # Nested block comment /* ... */
        if ch == "/" and nxt == "*":
            depth = 1
            out.extend((" ", " "))
            i += 2
            while i < n and depth > 0:
                if raw_sql[i] == "/" and i + 1 < n and raw_sql[i + 1] == "*":
                    depth += 1
                    out.extend((" ", " "))
                    i += 2
                elif raw_sql[i] == "*" and i + 1 < n and raw_sql[i + 1] == "/":
                    depth -= 1
                    out.extend((" ", " "))
                    i += 2
                else:
                    out.append(" ")
                    i += 1
            continue

        # Single-quoted string literal
        if ch == "'":
            out.append(" ")
            i += 1
            while i < n:
                out.append(" ")
                if raw_sql[i] == "'":
                    if i + 1 < n and raw_sql[i + 1] == "'":
                        out.append(" ")
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        # Double-quoted identifier: keep identifier characters (without ';')
        # so quoted function names such as "set_config" cannot bypass lexical checks.
        if ch == '"':
            out.append(" ")
            i += 1
            while i < n:
                if raw_sql[i] == '"':
                    if i + 1 < n and raw_sql[i + 1] == '"':
                        out.extend((" ", " "))
                        i += 2
                        continue
                    out.append(" ")
                    i += 1
                    break
                out.append(" " if raw_sql[i] == ";" else raw_sql[i])
                i += 1
            continue

        # Dollar-quoted string $$...$$ or $tag$...$tag$
        if ch == "$":
            tag_match = _DOLLAR_TAG_RE.match(raw_sql[i:])
            if tag_match:
                tag = tag_match.group(0)
                end = raw_sql.find(tag, i + len(tag))
                stop = n if end == -1 else end + len(tag)
                out.extend(" " for _ in range(stop - i))
                i = stop
                continue

        if ch == ";":
            semicolons.append(i)
            out.append(";")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out), semicolons
