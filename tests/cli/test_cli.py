"""Fast unit tests for ``tycoon-cli`` (``src/cli/``) with mocked HTTP transport."""

from __future__ import annotations

import ast
import io
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from cli.app import DEFAULT_BASE_URL, main, render_ascii_table

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_DIR = _REPO_ROOT / "src" / "cli"
_FORBIDDEN_PACKAGES = frozenset({"domain", "application", "infrastructure", "api"})


class _FakeTransport:
    def __init__(
        self,
        routes: dict[tuple[str, str], tuple[int, Any]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.routes = routes or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, request: urllib.request.Request, timeout: float
    ) -> tuple[int, str]:
        url = request.full_url
        method = request.get_method()
        headers = {k.lower(): v for k, v in request.header_items()}
        body_text = (
            request.data.decode("utf-8") if isinstance(request.data, bytes) else None
        )
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body_text,
                "timeout": timeout,
            }
        )
        if self.error is not None:
            raise self.error

        prefix = DEFAULT_BASE_URL
        path = url[len(prefix) :] if url.startswith(prefix) else url
        for candidate_prefix in ("https://prod.example.com", "http://127.0.0.1:8000"):
            if url.startswith(candidate_prefix):
                path = url[len(candidate_prefix) :]
                break

        status, payload = self.routes[(method, path)]
        if isinstance(payload, str):
            return status, payload
        return status, json.dumps(payload)


def _run_cli(
    argv: list[str],
    *,
    transport: _FakeTransport | None = None,
    stdin_text: str = "",
    inputs: list[str] | None = None,
    env_file: Path,
    challenges_dir: Path | None = None,
) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin = io.StringIO(stdin_text)
    it: Iterator[str] = iter(inputs or [])

    def _input(prompt: str) -> str:
        stdout.write(prompt)
        try:
            return next(it)
        except StopIteration as exc:
            raise EOFError() from exc

    code = main(
        argv,
        transport=transport,
        env_file=env_file,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        input_fn=_input,
        challenges_dir=challenges_dir,
    )
    return code, stdout.getvalue(), stderr.getvalue()


# --- Architectural isolation ------------------------------------------------


def test_cli_does_not_import_backend_layers() -> None:
    py_files = sorted(_CLI_DIR.rglob("*.py"))
    assert py_files
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    assert top not in _FORBIDDEN_PACKAGES, (
                        f"{py_file.name} imports forbidden module {alias.name!r}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                top = node.module.split(".", 1)[0]
                assert top not in _FORBIDDEN_PACKAGES, (
                    f"{py_file.name} imports from forbidden module {node.module!r}"
                )


# --- ASCII table formatting -------------------------------------------------


def test_render_ascii_table_aligns_cells_and_handles_empty() -> None:
    empty = render_ascii_table([], [])
    assert "Sin columnas" in empty

    zero_rows = render_ascii_table(["id", "nombre"], [])
    assert "| id | nombre |" in zero_rows
    assert "(0 filas)" in zero_rows

    rendered = render_ascii_table(
        ["id", "name", "email"],
        [[1, "Ana", None], [200, "Comercial Norte", "info@example.com"]],
    )
    lines = rendered.splitlines()
    assert len({len(line) for line in lines}) == 1
    assert "| 1   | Ana             | NULL             |" in rendered


# --- Subcommands ------------------------------------------------------------


def test_health_command_reports_ok_and_handles_network_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    env_file = tmp_path / "missing.env"
    transport = _FakeTransport({("GET", "/health"): (200, {"status": "ok"})})

    code, out, err = _run_cli(["health"], transport=transport, env_file=env_file)
    assert code == 0
    assert err == ""
    assert "Estado: ok" in out
    assert "ms)" in out

    broken = _FakeTransport(error=urllib.error.URLError("connection refused"))
    bad_code, _, bad_err = _run_cli(["health"], transport=broken, env_file=env_file)
    assert bad_code == 2
    assert "No se pudo conectar" in bad_err


@pytest.mark.parametrize(
    "argv",
    [
        ["--api-key", "super-secret", "--player-id", "42", "challenges"],
        ["challenges", "--api-key", "super-secret", "--player-id", "42"],
    ],
)
def test_challenges_accepts_global_flags_before_or_after_subcommand(
    tmp_path: Path, argv: list[str]
) -> None:
    transport = _FakeTransport(
        {
            ("GET", "/challenges"): (
                200,
                [
                    {
                        "code": "dedupe-row-number",
                        "module": "postgresql",
                        "title": "Eliminar duplicados",
                        "description": "Desc",
                        "difficulty": 1,
                    },
                    {
                        "code": "fix-multiplying-join",
                        "module": "postgresql",
                        "title": "Corregir JOIN",
                        "description": "Desc 2",
                        "difficulty": 2,
                    },
                ],
            ),
            ("GET", "/players/42/progress"): (
                200,
                {
                    "roblox_user_id": 42,
                    "completed": [
                        {
                            "code": "dedupe-row-number",
                            "completed_at": "2026-11-19T12:00:00Z",
                            "best_ms": 5,
                        }
                    ],
                },
            ),
        }
    )

    code, out, err = _run_cli(
        argv, transport=transport, env_file=tmp_path / "missing.env"
    )
    assert code == 0
    assert err == ""
    assert "dedupe-row-number" in out
    assert "Fácil" in out
    assert "Completado" in out
    assert "Pendiente" in out
    assert transport.calls[0]["headers"]["x-api-key"] == "super-secret"


def test_submit_supports_sql_file_stdin_exit_codes_and_quotes_code(
    tmp_path: Path,
) -> None:
    sql_file = tmp_path / "query.sql"
    sql_file.write_text("SELECT 1 AS ok;", encoding="utf-8")

    transport = _FakeTransport(
        {
            ("POST", "/challenges/dedupe-row-number/submit"): (
                200,
                {
                    "passed": True,
                    "execution_ms": 4,
                    "message": "¡Reto superado!",
                    "columns": ["id", "name"],
                    "preview_rows": [["1", "Ana"]],
                },
            ),
            ("POST", "/challenges/a%2Fb/submit"): (
                200,
                {
                    "passed": False,
                    "execution_ms": 3,
                    "message": "El resultado no coincide.",
                    "columns": ["id"],
                    "preview_rows": [["99"]],
                },
            ),
        }
    )
    env_file = tmp_path / "missing.env"

    c_sql, out_sql, _ = _run_cli(
        ["submit", "dedupe-row-number", "--sql", "SELECT 1;", "--api-key", "k"],
        transport=transport,
        env_file=env_file,
    )
    c_file, out_file, _ = _run_cli(
        ["--api-key", "k", "submit", "dedupe-row-number", "--file", str(sql_file)],
        transport=transport,
        env_file=env_file,
    )
    c_stdin, out_stdin, _ = _run_cli(
        ["submit", "a/b", "--api-key", "k"],
        transport=transport,
        stdin_text="SELECT 99 AS id;",
        env_file=env_file,
    )

    assert c_sql == 0
    assert c_file == 0
    assert "[PASS] (4 ms)" in out_sql
    assert "| 1  | Ana  |" in out_file
    assert c_stdin == 1
    assert "[FAIL] (3 ms)" in out_stdin
    assert "| 99 |" in out_stdin
    assert transport.calls[-1]["url"].endswith("/challenges/a%2Fb/submit")


def test_progress_command_renders_empty_and_completed(tmp_path: Path) -> None:
    env_file = tmp_path / "missing.env"
    empty_transport = _FakeTransport(
        {
            ("GET", "/players/7/progress"): (
                200,
                {"roblox_user_id": 7, "completed": []},
            )
        }
    )
    code, out, _ = _run_cli(
        ["progress", "--player-id", "7", "--api-key", "k"],
        transport=empty_transport,
        env_file=env_file,
    )
    assert code == 0
    assert "Aún no has completado" in out

    done_transport = _FakeTransport(
        {
            ("GET", "/players/7/progress"): (
                200,
                {
                    "roblox_user_id": 7,
                    "completed": [
                        {
                            "code": "dedupe-row-number",
                            "completed_at": "2026-11-19T12:00:00Z",
                            "best_ms": 6,
                        }
                    ],
                },
            )
        }
    )
    code2, out2, _ = _run_cli(
        ["progress", "--player-id", "7", "--api-key", "k"],
        transport=done_transport,
        env_file=env_file,
    )
    assert code2 == 0
    assert "dedupe-row-number" in out2
    assert "6" in out2


def test_play_interactive_flow_supports_hints_multiline_and_quit(
    tmp_path: Path,
) -> None:
    pack_dir = tmp_path / "challenges" / "dedupe-row-number"
    pack_dir.mkdir(parents=True)
    (pack_dir / "challenge.toml").write_text(
        'hints = ["Usa ROW_NUMBER()."]\n'
        'starter_sql = "SELECT * FROM staging_customers;"\n',
        encoding="utf-8",
    )

    transport = _FakeTransport(
        {
            ("GET", "/challenges"): (
                200,
                [
                    {
                        "code": "dedupe-row-number",
                        "module": "postgresql",
                        "title": "Eliminar duplicados",
                        "description": "Enunciado de prueba.",
                        "difficulty": 1,
                    }
                ],
            ),
            ("GET", "/players/1/progress"): (
                200,
                {"roblox_user_id": 1, "completed": []},
            ),
            ("POST", "/challenges/dedupe-row-number/submit"): (
                200,
                {
                    "passed": True,
                    "execution_ms": 8,
                    "message": "¡Reto superado!",
                    "columns": ["customer_id"],
                    "preview_rows": [["1"]],
                },
            ),
        }
    )

    code, out, err = _run_cli(
        ["play", "--api-key", "k"],
        transport=transport,
        inputs=[
            "1",
            ":pista",
            "SELECT customer_id",
            "FROM ranked;",
            "",
            ":retos",
            ":quit",
        ],
        env_file=tmp_path / "missing.env",
        challenges_dir=tmp_path / "challenges",
    )

    assert code == 0
    assert err == ""
    assert "Usa ROW_NUMBER()." in out
    assert "[PASS] (8 ms) ¡Reto superado!" in out
    assert "| 1           |" in out


# --- HTTP error handling and zero secret leakage ----------------------------


@pytest.mark.parametrize(
    ("status", "payload", "expected_fragment"),
    [
        (401, {"detail": "Falta el encabezado X-API-Key."}, "autenticación"),
        (403, {"detail": "Clave de API inválida."}, "autenticación"),
        (404, {"detail": "Reto no encontrado."}, "no encontrado"),
        (422, {"detail": "La consulta SQL no puede estar vacía."}, "vacía"),
        (503, {"detail": "El evaluador no está disponible."}, "disponible"),
    ],
)
def test_http_errors_map_cleanly_without_leaking_api_key(
    tmp_path: Path,
    status: int,
    payload: dict[str, Any],
    expected_fragment: str,
) -> None:
    secret_key = "TOP-SECRET-KEY-999"
    transport = _FakeTransport(
        {("POST", "/challenges/dedupe-row-number/submit"): (status, payload)}
    )

    code, out, err = _run_cli(
        [
            "submit",
            "dedupe-row-number",
            "--sql",
            "SELECT 1",
            "--api-key",
            secret_key,
        ],
        transport=transport,
        env_file=tmp_path / "missing.env",
    )

    assert code == 2
    assert expected_fragment in err.lower()
    assert secret_key not in out
    assert secret_key not in err


def test_network_timeout_and_urlerror_do_not_leak_api_key(tmp_path: Path) -> None:
    secret_key = "ULTRA-SECRET-KEY-ABC"
    env_file = tmp_path / "missing.env"

    timeout_transport = _FakeTransport(error=TimeoutError("timed out"))
    code1, out1, err1 = _run_cli(
        ["challenges", "--api-key", secret_key],
        transport=timeout_transport,
        env_file=env_file,
    )
    assert code1 == 2
    assert "tiempo de espera agotado" in err1.lower()
    assert secret_key not in out1 + err1

    down_transport = _FakeTransport(
        error=urllib.error.URLError(f"refused with {secret_key}")
    )
    code2, out2, err2 = _run_cli(
        ["challenges", "--api-key", secret_key],
        transport=down_transport,
        env_file=env_file,
    )
    assert code2 == 2
    assert "no se pudo conectar" in err2.lower()
    assert secret_key not in out2 + err2
