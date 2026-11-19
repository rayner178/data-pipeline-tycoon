"""Isolated, least-privilege PostgreSQL SQL sandbox evaluator (SPEC section 7)."""

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

from application.errors import EvaluatorError
from application.evaluation import EvaluationResult, ExecutionFailed, ExecutionSucceeded
from application.ports import SolutionEvaluator
from domain.entities import Challenge
from domain.result_matching import Cell, FrozenResult

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
        max_rows: int = MAX_RESULT_ROWS,
        max_sql_length: int = MAX_SQL_LENGTH,
    ) -> None:
        self._admin_engine = admin_engine
        self._max_rows = max_rows
        self._max_sql_length = max_sql_length
        self._sandbox_password = secrets.token_urlsafe(32)
        self._provisioned = False

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
        return self._make_conninfo(
            user=SANDBOX_ROLE,
            password=self._sandbox_password,
        )

    def _make_conninfo(self, *, user: str, password: str) -> str:
        url = self._admin_engine.url
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
        except psycopg.Error as exc:
            raise EvaluatorError("Failed to provision PostgreSQL sandbox role") from exc
        self._provisioned = True

    def _provision_role_and_locks(self, conn: psycopg.Connection[Any]) -> None:
        db_name = self._admin_engine.url.database or "postgres"
        role_ident = pg_sql.Identifier(SANDBOX_ROLE)
        db_ident = pg_sql.Identifier(db_name)
        password_lit = pg_sql.Literal(self._sandbox_password)

        role_exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s",
            (SANDBOX_ROLE,),
        ).fetchone()
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
            conn.execute(stmt)

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

        for fn_signature in _DANGEROUS_FUNCTIONS:
            try:
                conn.execute(
                    f"REVOKE EXECUTE ON FUNCTION {fn_signature} "
                    f"FROM PUBLIC, {SANDBOX_ROLE}"
                )
            except (UndefinedFunction, InsufficientPrivilege):
                continue

    def _prepare_schema(self, schema_name: str, setup_sql: str) -> None:
        schema_ident = pg_sql.Identifier(schema_name)
        role_ident = pg_sql.Identifier(SANDBOX_ROLE)
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
            return ExecutionFailed(
                error_message=_sanitize_pg_error(exc),
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


def _sanitize_pg_error(exc: psycopg.Error) -> str:
    primary = exc.diag.message_primary if exc.diag is not None else None
    raw = primary or str(exc).splitlines()[0]
    cleaned = _SANDBOX_SCHEMA_RE.sub("sandbox", raw)
    cleaned = _INTERNAL_NAMES_RE.sub("sandbox_user", cleaned)
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
