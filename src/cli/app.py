"""Lightweight, zero-dependency HTTP CLI client for Data Pipeline Tycoon."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_PLAYER_ID = 1
DEFAULT_TIMEOUT_SECONDS = 65.0

_DIFFICULTY_LABELS = {1: "Fácil", 2: "Media", 3: "Difícil"}
_LOCAL_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DEFAULT_CHALLENGES_DIR = Path(__file__).resolve().parents[2] / "challenges"
_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

TransportCallable = Callable[[urllib.request.Request, float], tuple[int, str]]
InputCallable = Callable[[str], str]


class CliError(Exception):
    """Expected user-facing error mapped cleanly without internal tracebacks."""


@dataclass(frozen=True, slots=True)
class CliConfig:
    base_url: str
    api_key: str
    player_id: int
    timeout: float


def _redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


def _read_dotenv_var(name: str, env_file: Path) -> str | None:
    if not env_file.is_file():
        return None
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def _lookup_setting(name: str, env_file: Path | None) -> str | None:
    raw = os.environ.get(name)
    if raw is not None and raw.strip():
        return raw.strip()
    target_env = env_file if env_file is not None else _find_default_env_file()
    if target_env is None:
        return None
    val = _read_dotenv_var(name, target_env)
    return val.strip() if val is not None and val.strip() else None


def _find_default_env_file() -> Path | None:
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env
    if _DEFAULT_ENV_PATH.is_file():
        return _DEFAULT_ENV_PATH
    return None


def resolve_config(
    args: argparse.Namespace, *, env_file: Path | None = None
) -> CliConfig:
    """Resolve CLI options from flags -> env -> optional .env -> defaults."""
    raw_base_url = getattr(args, "base_url", None)
    if raw_base_url is None:
        raw_base_url = _lookup_setting("TYCOON_BASE_URL", env_file) or DEFAULT_BASE_URL
    base_url = str(raw_base_url).strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise CliError(
            "La URL base (--base-url / TYCOON_BASE_URL) debe iniciar con http:// o https://."
        )

    raw_api_key = getattr(args, "api_key", None)
    if raw_api_key is None:
        raw_api_key = _lookup_setting("API_KEY", env_file) or ""
    api_key = str(raw_api_key).strip()

    raw_player_id = getattr(args, "player_id", None)
    if raw_player_id is None:
        raw_player_str = _lookup_setting("TYCOON_PLAYER_ID", env_file)
        if raw_player_str is not None:
            try:
                player_id = int(raw_player_str)
            except ValueError as exc:
                raise CliError("TYCOON_PLAYER_ID debe ser un entero positivo.") from exc
        else:
            player_id = DEFAULT_PLAYER_ID
    else:
        player_id = int(raw_player_id)
    if player_id <= 0:
        raise CliError("--player-id debe ser un entero mayor que 0.")

    raw_timeout = getattr(args, "timeout", None)
    if raw_timeout is None:
        raw_timeout_str = _lookup_setting("TYCOON_TIMEOUT", env_file)
        if raw_timeout_str is not None:
            try:
                timeout = float(raw_timeout_str)
            except ValueError as exc:
                raise CliError("TYCOON_TIMEOUT debe ser un número positivo.") from exc
        else:
            timeout = DEFAULT_TIMEOUT_SECONDS
    else:
        timeout = float(raw_timeout)
    if timeout <= 0:
        raise CliError("--timeout debe ser mayor que 0 segundos.")

    return CliConfig(
        base_url=base_url,
        api_key=api_key,
        player_id=player_id,
        timeout=timeout,
    )


def default_urllib_transport(
    request: urllib.request.Request, timeout: float
) -> tuple[int, str]:
    """Execute a request using stdlib urllib and return (status_code, body_text)."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body_bytes: bytes = response.read()
            return int(response.status), body_bytes.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        err_bytes = exc.read()
        err_text = err_bytes.decode("utf-8", errors="replace") if err_bytes else ""
        return int(exc.code), err_text


class TycoonHttpClient:
    """HTTP client talking strictly to the Data Pipeline Tycoon REST API."""

    def __init__(
        self,
        config: CliConfig,
        *,
        transport: TransportCallable | None = None,
    ) -> None:
        self._config = config
        self._transport = (
            transport if transport is not None else default_urllib_transport
        )

    def health(self) -> tuple[dict[str, Any], int]:
        payload, elapsed_ms = self._request_json("GET", "/health", require_auth=False)
        if not isinstance(payload, dict):
            raise CliError("Respuesta inesperada del endpoint /health.")
        return payload, elapsed_ms

    def list_challenges(self) -> list[dict[str, Any]]:
        payload, _ = self._request_json("GET", "/challenges", require_auth=True)
        if not isinstance(payload, list):
            raise CliError("Formato inesperado al recibir la lista de retos.")
        return [item for item in payload if isinstance(item, dict)]

    def get_progress(self, player_id: int) -> dict[str, Any]:
        payload, _ = self._request_json(
            "GET", f"/players/{player_id}/progress", require_auth=True
        )
        if not isinstance(payload, dict):
            raise CliError("Formato inesperado al recibir el progreso del jugador.")
        return payload

    def submit_solution(self, *, code: str, player_id: int, sql: str) -> dict[str, Any]:
        encoded_code = urllib.parse.quote(code, safe="")
        payload, _ = self._request_json(
            "POST",
            f"/challenges/{encoded_code}/submit",
            body={"roblox_user_id": player_id, "sql": sql},
            require_auth=True,
        )
        if not isinstance(payload, dict):
            raise CliError("Formato inesperado al recibir el veredicto del envío.")
        return payload

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        require_auth: bool,
    ) -> tuple[Any, int]:
        if require_auth and not self._config.api_key:
            raise CliError(
                "Falta API_KEY: pasa --api-key o define la variable de entorno API_KEY."
            )

        headers: dict[str, str] = {"Accept": "application/json"}
        if require_auth:
            headers["X-API-Key"] = self._config.api_key

        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        url = f"{self._config.base_url}{path}"
        request = urllib.request.Request(
            url=url, data=data, headers=headers, method=method
        )

        started = time.perf_counter()
        try:
            status_code, raw_body = self._transport(request, self._config.timeout)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise CliError(
                    f"Tiempo de espera agotado ({self._config.timeout:g} s) "
                    f"esperando respuesta de {self._config.base_url}."
                ) from exc
            safe_reason = _redact_secret(str(exc.reason), self._config.api_key)
            raise CliError(
                f"No se pudo conectar con {self._config.base_url} ({safe_reason})."
            ) from exc
        except TimeoutError as exc:
            raise CliError(
                f"Tiempo de espera agotado ({self._config.timeout:g} s) "
                f"esperando respuesta de {self._config.base_url}."
            ) from exc
        except OSError as exc:
            safe_err = _redact_secret(str(exc), self._config.api_key)
            raise CliError(
                f"Error de red al conectar con {self._config.base_url}: {safe_err}"
            ) from exc

        elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
        if status_code >= 400:
            raise CliError(
                _redact_secret(
                    _format_http_error(status_code, raw_body), self._config.api_key
                )
            )

        if not raw_body.strip():
            return {}, elapsed_ms
        try:
            return json.loads(raw_body), elapsed_ms
        except json.JSONDecodeError as exc:
            raise CliError("El servidor devolvió una respuesta JSON inválida.") from exc


def _format_http_error(status_code: int, raw_body: str) -> str:
    detail = _extract_error_detail(raw_body)
    if status_code in (401, 403):
        return (
            f"Error de autenticación (HTTP {status_code}): "
            "verifica tu API_KEY o --api-key."
        )
    if status_code == 404:
        return detail or "Recurso o reto no encontrado (HTTP 404)."
    if status_code == 422:
        return (
            detail
            or "La consulta SQL o los parámetros enviados no son válidos (HTTP 422)."
        )
    if status_code == 503:
        return (
            detail
            or "El evaluador SQL no está disponible en este momento (HTTP 503). "
            "Intenta de nuevo."
        )
    if status_code >= 500:
        return f"Error interno del servidor (HTTP {status_code}). Intenta más tarde."
    return detail or f"Error HTTP inesperado ({status_code})."


def _extract_error_detail(raw_body: str) -> str | None:
    if not raw_body.strip():
        return None
    try:
        decoded = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, dict):
        detail = decoded.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg")
                if isinstance(msg, str):
                    return msg
    return None


def _sanitize_cell(value: object) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
    return text


def render_ascii_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Render headers and rows as an aligned ASCII table."""
    clean_headers = [_sanitize_cell(h) for h in headers]
    if not clean_headers:
        if not rows:
            return "(Sin columnas ni filas de salida)"
        col_count = max(len(r) for r in rows)
        clean_headers = [f"col_{i + 1}" for i in range(col_count)]

    col_count = len(clean_headers)
    normalized_rows: list[list[str]] = []
    for row in rows:
        cells = [
            _sanitize_cell(row[i]) if i < len(row) else "" for i in range(col_count)
        ]
        normalized_rows.append(cells)

    widths = [len(h) for h in clean_headers]
    for row_cells in normalized_rows:
        for idx, cell in enumerate(row_cells):
            if len(cell) > widths[idx]:
                widths[idx] = len(cell)

    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [
        border,
        "| "
        + " | ".join(h.ljust(widths[idx]) for idx, h in enumerate(clean_headers))
        + " |",
        border,
    ]
    if not normalized_rows:
        lines.append("(0 filas)")
    else:
        for row_cells in normalized_rows:
            lines.append(
                "| "
                + " | ".join(
                    row_cells[idx].ljust(widths[idx]) for idx in range(col_count)
                )
                + " |"
            )
        lines.append(border)
    return "\n".join(lines)


def _difficulty_text(value: object) -> str:
    if isinstance(value, int) and value in _DIFFICULTY_LABELS:
        return _DIFFICULTY_LABELS[value]
    return str(value)


def _load_local_challenge_extras(
    code: str, *, challenges_dir: Path | None = None
) -> tuple[tuple[str, ...], str | None]:
    if not _LOCAL_SLUG_RE.match(code):
        return (), None
    root = challenges_dir if challenges_dir is not None else _DEFAULT_CHALLENGES_DIR
    toml_path = root / code / "challenge.toml"
    if not toml_path.is_file():
        return (), None
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return (), None
    raw_hints = data.get("hints")
    hints: tuple[str, ...] = ()
    if isinstance(raw_hints, list):
        hints = tuple(
            item.strip() for item in raw_hints if isinstance(item, str) and item.strip()
        )
    raw_starter = data.get("starter_sql")
    starter = (
        raw_starter.strip()
        if isinstance(raw_starter, str) and raw_starter.strip()
        else None
    )
    return hints, starter


def _completed_map_from_progress(progress: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_completed = progress.get("completed")
    if not isinstance(raw_completed, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in raw_completed:
        if isinstance(entry, dict) and isinstance(entry.get("code"), str):
            result[entry["code"]] = entry
    return result


def _render_challenges_overview(
    challenges: Sequence[dict[str, Any]],
    completed_by_code: dict[str, dict[str, Any]],
) -> str:
    table_rows: list[list[object]] = []
    for item in challenges:
        code = str(item.get("code", ""))
        done = completed_by_code.get(code)
        status = "Completado" if done is not None else "Pendiente"
        best = done.get("best_ms") if done is not None else None
        table_rows.append(
            [
                code,
                _difficulty_text(item.get("difficulty", "")),
                str(item.get("title", "")),
                status,
                best if best is not None else "-",
            ]
        )
    return render_ascii_table(
        ["Código", "Dificultad", "Título", "Estado", "Mejor (ms)"],
        table_rows,
    )


def _cmd_health(client: TycoonHttpClient, stdout: TextIO) -> int:
    payload, elapsed_ms = client.health()
    status = payload.get("status", "unknown")
    stdout.write(f"Estado: {status} ({elapsed_ms} ms)\n")
    return 0


def _cmd_challenges(client: TycoonHttpClient, config: CliConfig, stdout: TextIO) -> int:
    challenges = client.list_challenges()
    completed_by_code: dict[str, dict[str, Any]] = {}
    if config.api_key:
        try:
            progress = client.get_progress(config.player_id)
            completed_by_code = _completed_map_from_progress(progress)
        except CliError as exc:
            if "autenticación" in str(exc).lower():
                raise
    stdout.write(_render_challenges_overview(challenges, completed_by_code) + "\n")
    return 0


def _read_sql_from_args(args: argparse.Namespace, stdin: TextIO) -> str:
    raw_sql: str | None = getattr(args, "sql", None)
    raw_file: str | None = getattr(args, "file", None)
    if raw_sql is not None:
        sql = raw_sql
    elif raw_file is not None:
        sql_path = Path(raw_file)
        if not sql_path.is_file():
            raise CliError(f"No se encontró el archivo SQL: {sql_path}")
        try:
            sql = sql_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CliError(f"No se pudo leer {sql_path}: {exc}") from exc
    else:
        sql = stdin.read()

    if not sql.strip():
        raise CliError("La consulta SQL no puede estar vacía.")
    return sql


def _print_submission_result(payload: dict[str, Any], stdout: TextIO) -> int:
    passed = bool(payload.get("passed"))
    execution_ms = payload.get("execution_ms")
    message = str(payload.get("message", ""))
    columns = payload.get("columns")
    preview_rows = payload.get("preview_rows")

    verdict = "PASS" if passed else "FAIL"
    timing = f" ({execution_ms} ms)" if isinstance(execution_ms, int) else ""
    stdout.write(f"[{verdict}]{timing} {message}\n")

    col_list = [str(c) for c in columns] if isinstance(columns, list) else []
    row_list = (
        [list(r) for r in preview_rows if isinstance(r, list)]
        if isinstance(preview_rows, list)
        else []
    )
    if col_list or row_list:
        stdout.write(render_ascii_table(col_list, row_list) + "\n")
    return 0 if passed else 1


def _cmd_submit(
    client: TycoonHttpClient,
    config: CliConfig,
    args: argparse.Namespace,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    code = str(args.code).strip()
    if not code:
        raise CliError("Debes indicar un código de reto válido.")
    sql = _read_sql_from_args(args, stdin)
    payload = client.submit_solution(code=code, player_id=config.player_id, sql=sql)
    return _print_submission_result(payload, stdout)


def _cmd_progress(client: TycoonHttpClient, config: CliConfig, stdout: TextIO) -> int:
    progress = client.get_progress(config.player_id)
    completed = progress.get("completed")
    stdout.write(
        f"Jugador Roblox ID: {progress.get('roblox_user_id', config.player_id)}\n"
    )
    if not isinstance(completed, list) or not completed:
        stdout.write("Aún no has completado ningún reto.\n")
        return 0
    rows = [
        [
            str(entry.get("code", "")),
            entry.get("best_ms", "-"),
            str(entry.get("completed_at", "")),
        ]
        for entry in completed
        if isinstance(entry, dict)
    ]
    stdout.write(
        render_ascii_table(["Código", "Mejor (ms)", "Completado en"], rows) + "\n"
    )
    return 0


def _select_challenge_interactively(
    challenges: Sequence[dict[str, Any]],
    completed_by_code: dict[str, dict[str, Any]],
    *,
    stdout: TextIO,
    input_fn: InputCallable,
) -> dict[str, Any] | None:
    while True:
        stdout.write("\n=== Data Pipeline Tycoon — Retos disponibles ===\n")
        indexed_rows = [
            [
                idx + 1,
                str(item.get("code", "")),
                _difficulty_text(item.get("difficulty", "")),
                str(item.get("title", "")),
                "Completado"
                if str(item.get("code", "")) in completed_by_code
                else "Pendiente",
                completed_by_code.get(str(item.get("code", "")), {}).get(
                    "best_ms", "-"
                ),
            ]
            for idx, item in enumerate(challenges)
        ]
        stdout.write(
            render_ascii_table(
                ["#", "Código", "Dificultad", "Título", "Estado", "Mejor (ms)"],
                indexed_rows,
            )
            + "\n"
        )
        try:
            choice = input_fn(
                "Elige un reto por número o código (:quit para salir): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            stdout.write("\n")
            return None

        if choice.lower() in {":quit", ":exit", "q", "quit"}:
            return None
        if choice.isdigit():
            pos = int(choice) - 1
            if 0 <= pos < len(challenges):
                return challenges[pos]
        for item in challenges:
            if str(item.get("code", "")) == choice:
                return item
        stdout.write("Selección no válida. Intenta con el número o código del reto.\n")


def _play_single_challenge(
    client: TycoonHttpClient,
    config: CliConfig,
    challenge: dict[str, Any],
    *,
    stdout: TextIO,
    stderr: TextIO,
    input_fn: InputCallable,
    challenges_dir: Path | None,
) -> tuple[bool, bool]:
    """Run REPL for one challenge; return (should_exit, passed_any)."""
    code = str(challenge.get("code", ""))
    title = str(challenge.get("title", ""))
    description = str(challenge.get("description", ""))
    difficulty = _difficulty_text(challenge.get("difficulty", ""))
    hints, starter_sql = _load_local_challenge_extras(
        code, challenges_dir=challenges_dir
    )

    stdout.write(f"\n--- [{code}] {title} ({difficulty}) ---\n")
    stdout.write(f"{description}\n")
    stdout.write(
        "Comandos: :run (ejecutar) | :pista | :plantilla | :reset | :retos | :quit\n"
        "Escribe SQL multilínea; envía con :run o línea vacía tras ';'.\n"
    )

    buffer: list[str] = []
    hint_idx = 0
    solved_now = False

    while True:
        prompt = "sql> " if not buffer else "...> "
        try:
            line = input_fn(prompt)
        except (EOFError, KeyboardInterrupt):
            stdout.write("\n")
            return True, solved_now

        cmd = line.strip().lower()
        if cmd in {":quit", ":exit"}:
            return True, solved_now
        if cmd in {":retos", ":back"}:
            return False, solved_now
        if cmd == ":reset":
            buffer.clear()
            stdout.write("Editor reiniciado.\n")
            continue
        if cmd in {":pista", ":hint"}:
            if not hints:
                stdout.write("No hay pistas locales disponibles para este reto.\n")
            else:
                stdout.write(f"{hints[hint_idx % len(hints)]}\n")
                hint_idx += 1
            continue
        if cmd in {":plantilla", ":starter"}:
            if starter_sql is None:
                stdout.write("No hay plantilla local disponible para este reto.\n")
            else:
                buffer = starter_sql.splitlines()
                stdout.write(f"Plantilla cargada:\n{starter_sql}\n")
            continue

        should_execute = False
        if cmd == ":run":
            should_execute = True
        elif line == "" and buffer and "\n".join(buffer).rstrip().endswith(";"):
            should_execute = True
        elif line != "" or buffer:
            buffer.append(line)

        if not should_execute:
            continue

        sql_text = "\n".join(buffer).strip()
        buffer.clear()
        if not sql_text:
            stdout.write("Escribe una consulta SELECT antes de ejecutar.\n")
            continue

        try:
            result = client.submit_solution(
                code=code, player_id=config.player_id, sql=sql_text
            )
            exit_code = _print_submission_result(result, stdout)
            if exit_code == 0:
                solved_now = True
        except CliError as exc:
            stderr.write(f"Error: {exc}\n")


def _cmd_play(
    client: TycoonHttpClient,
    config: CliConfig,
    *,
    stdout: TextIO,
    stderr: TextIO,
    input_fn: InputCallable,
    challenges_dir: Path | None,
) -> int:
    challenges = client.list_challenges()
    if not challenges:
        stdout.write("No hay retos disponibles en el servidor.\n")
        return 0

    completed_by_code = _completed_map_from_progress(
        client.get_progress(config.player_id)
    )
    while True:
        selected = _select_challenge_interactively(
            challenges, completed_by_code, stdout=stdout, input_fn=input_fn
        )
        if selected is None:
            return 0
        should_exit, solved_now = _play_single_challenge(
            client,
            config,
            selected,
            stdout=stdout,
            stderr=stderr,
            input_fn=input_fn,
            challenges_dir=challenges_dir,
        )
        if solved_now:
            try:
                completed_by_code = _completed_map_from_progress(
                    client.get_progress(config.player_id)
                )
            except CliError:
                pass
        if should_exit:
            return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser accepting shared options before or after commands."""
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--base-url",
        default=argparse.SUPPRESS,
        help="URL base de la API (por defecto TYCOON_BASE_URL o http://127.0.0.1:8000)",
    )
    shared.add_argument(
        "--api-key",
        default=argparse.SUPPRESS,
        help="Clave X-API-Key (por defecto variable de entorno API_KEY)",
    )
    shared.add_argument(
        "--player-id",
        type=int,
        default=argparse.SUPPRESS,
        help="ID positivo de jugador (por defecto TYCOON_PLAYER_ID o 1)",
    )
    shared.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="Timeout HTTP en segundos (por defecto TYCOON_TIMEOUT o 65.0)",
    )

    parser = argparse.ArgumentParser(
        prog="tycoon-cli",
        description="Cliente terminal para practicar SQL en Data Pipeline Tycoon.",
        parents=[shared],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "health",
        parents=[shared],
        help="Verifica GET /health y mide latencia en ms.",
    )
    subparsers.add_parser(
        "challenges",
        parents=[shared],
        help="Lista los retos disponibles en tabla ASCII.",
    )
    submit_parser = subparsers.add_parser(
        "submit",
        parents=[shared],
        help="Envía una consulta SQL contra un reto.",
    )
    submit_parser.add_argument("code", help="Código del reto (ej. dedupe-row-number)")
    source_group = submit_parser.add_mutually_exclusive_group()
    source_group.add_argument("--sql", help="Consulta SQL inline")
    source_group.add_argument("--file", help="Ruta a un archivo .sql")

    subparsers.add_parser(
        "progress",
        parents=[shared],
        help="Muestra los retos completados del jugador.",
    )
    subparsers.add_parser(
        "play",
        parents=[shared],
        help="Inicia el modo interactivo en terminal.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: TransportCallable | None = None,
    env_file: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    input_fn: InputCallable = input,
    challenges_dir: Path | None = None,
) -> int:
    """CLI entrypoint returning process exit status code."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    in_stream = stdin if stdin is not None else sys.stdin

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        config = resolve_config(args, env_file=env_file)
        client = TycoonHttpClient(config, transport=transport)
        if args.command == "health":
            return _cmd_health(client, out)
        if args.command == "challenges":
            return _cmd_challenges(client, config, out)
        if args.command == "submit":
            return _cmd_submit(client, config, args, in_stream, out)
        if args.command == "progress":
            return _cmd_progress(client, config, out)
        if args.command == "play":
            return _cmd_play(
                client,
                config,
                stdout=out,
                stderr=err,
                input_fn=input_fn,
                challenges_dir=challenges_dir,
            )
    except CliError as exc:
        err.write(f"Error: {exc}\n")
        return 2

    err.write(f"Error: Comando no reconocido: {args.command}\n")
    return 2
