"""Declarative loader and validator for SQL challenge packs in ``challenges/``."""

from __future__ import annotations

import json
import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from domain.entities import Challenge, Difficulty
from domain.errors import DomainValidationError
from domain.result_matching import FrozenResult
from infrastructure.serialization import deserialize_expected_result

DEFAULT_CHALLENGES_DIR = Path(__file__).resolve().parents[2] / "challenges"

REQUIRED_PACK_FILES = (
    "challenge.toml",
    "setup.sql",
    "expected_result.json",
    "solution.sql",
    "wrong_solution.sql",
)

_CODE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REQUIRED_TOML_KEYS = frozenset(
    {"code", "module", "title", "description", "difficulty", "max_seconds", "ordered"}
)
_OPTIONAL_TOML_KEYS = frozenset({"id", "hints", "starter_sql"})
_ALLOWED_TOML_KEYS = _REQUIRED_TOML_KEYS | _OPTIONAL_TOML_KEYS
_DIFFICULTY_NAMES = {
    "EASY": Difficulty.EASY,
    "MEDIUM": Difficulty.MEDIUM,
    "HARD": Difficulty.HARD,
}


class ChallengePackError(ValueError):
    """Raised when a declarative challenge pack is missing files or invalid."""


@dataclass(frozen=True, slots=True)
class ChallengePack:
    challenge: Challenge
    solution_sql: str
    wrong_solution_sql: str
    hints: tuple[str, ...]
    starter_sql: str | None
    directory: Path


def load_challenge_pack(pack_dir: Path) -> ChallengePack:
    """Load and strictly validate a single challenge directory."""
    if not pack_dir.is_dir():
        raise ChallengePackError(f"Challenge pack directory does not exist: {pack_dir}")

    _ensure_required_files(pack_dir)
    meta = _parse_toml_manifest(
        pack_dir / "challenge.toml", expected_code=pack_dir.name
    )

    setup_sql = _read_nonblank_text(pack_dir / "setup.sql", "setup.sql")
    solution_sql = _read_nonblank_text(pack_dir / "solution.sql", "solution.sql")
    wrong_solution_sql = _read_nonblank_text(
        pack_dir / "wrong_solution.sql", "wrong_solution.sql"
    )
    expected_result = _load_expected_result(pack_dir / "expected_result.json")

    code = _require_nonblank_str(meta["code"], "code")
    if not _CODE_RE.match(code):
        raise ChallengePackError(
            f"Challenge code {code!r} must be strict kebab-case (a-z, 0-9, '-')"
        )
    if code != pack_dir.name:
        raise ChallengePackError(
            f"Challenge code {code!r} must match directory name {pack_dir.name!r}"
        )

    challenge_id = _resolve_challenge_id(meta.get("id"), code)
    difficulty = _parse_difficulty(meta["difficulty"])
    max_seconds = _parse_max_seconds(meta["max_seconds"])
    ordered = meta["ordered"]
    if not isinstance(ordered, bool):
        raise ChallengePackError("challenge.toml field 'ordered' must be a boolean")

    hints = _parse_hints(meta.get("hints"))
    starter_sql = _parse_starter_sql(meta.get("starter_sql"))

    try:
        challenge = Challenge(
            id=challenge_id,
            code=code,
            module=_require_nonblank_str(meta["module"], "module"),
            title=_require_nonblank_str(meta["title"], "title"),
            description=_require_nonblank_str(meta["description"], "description"),
            difficulty=difficulty,
            setup_sql=setup_sql,
            expected_result=expected_result,
            max_seconds=max_seconds,
            ordered=ordered,
        )
    except DomainValidationError as exc:
        raise ChallengePackError(f"Invalid challenge {code!r}: {exc}") from exc

    return ChallengePack(
        challenge=challenge,
        solution_sql=solution_sql,
        wrong_solution_sql=wrong_solution_sql,
        hints=hints,
        starter_sql=starter_sql,
        directory=pack_dir,
    )


def load_all_challenge_packs(
    challenges_root: Path = DEFAULT_CHALLENGES_DIR,
) -> tuple[ChallengePack, ...]:
    """Discover, validate and return all challenge packs sorted by difficulty, code."""
    if not challenges_root.is_dir():
        raise ChallengePackError(
            f"Challenges directory does not exist: {challenges_root}"
        )

    pack_dirs = sorted(
        p
        for p in challenges_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
    if not pack_dirs:
        raise ChallengePackError(f"No challenge packs found in {challenges_root}")

    packs: list[ChallengePack] = []
    seen_codes: set[str] = set()
    seen_ids: set[UUID] = set()
    for pack_dir in pack_dirs:
        pack = load_challenge_pack(pack_dir)
        if pack.challenge.code in seen_codes:
            raise ChallengePackError(
                f"Duplicate challenge code: {pack.challenge.code!r}"
            )
        if pack.challenge.id in seen_ids:
            raise ChallengePackError(f"Duplicate challenge UUID: {pack.challenge.id}")
        seen_codes.add(pack.challenge.code)
        seen_ids.add(pack.challenge.id)
        packs.append(pack)

    packs.sort(key=lambda item: (int(item.challenge.difficulty), item.challenge.code))
    return tuple(packs)


def load_all_challenges(
    challenges_root: Path = DEFAULT_CHALLENGES_DIR,
) -> tuple[Challenge, ...]:
    """Load validated Challenge domain entities from the declarative catalog."""
    return tuple(pack.challenge for pack in load_all_challenge_packs(challenges_root))


def _ensure_required_files(pack_dir: Path) -> None:
    missing = [name for name in REQUIRED_PACK_FILES if not (pack_dir / name).is_file()]
    if missing:
        raise ChallengePackError(
            f"Challenge pack {pack_dir.name!r} is missing files: {', '.join(missing)}"
        )


def _parse_toml_manifest(path: Path, *, expected_code: str) -> dict[str, Any]:
    try:
        raw_data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ChallengePackError(
            f"Invalid TOML in {expected_code}/challenge.toml: {exc}"
        ) from exc

    missing = sorted(_REQUIRED_TOML_KEYS - raw_data.keys())
    if missing:
        raise ChallengePackError(
            f"Missing keys in {expected_code}/challenge.toml: {', '.join(missing)}"
        )
    unknown = sorted(raw_data.keys() - _ALLOWED_TOML_KEYS)
    if unknown:
        raise ChallengePackError(
            f"Unknown keys in {expected_code}/challenge.toml: {', '.join(unknown)}"
        )
    return raw_data


def _read_nonblank_text(path: Path, label: str) -> str:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ChallengePackError(f"Failed to read {path}: {exc}") from exc
    if not content:
        raise ChallengePackError(f"{label} in {path.parent.name!r} cannot be empty")
    return content


def _load_expected_result(path: Path) -> FrozenResult:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChallengePackError(f"Invalid JSON in {path}: {exc}") from exc
    try:
        frozen = deserialize_expected_result(raw_payload)
    except ValueError as exc:
        raise ChallengePackError(f"Invalid expected_result in {path}: {exc}") from exc
    if not frozen:
        raise ChallengePackError(
            f"expected_result in {path.parent.name!r} must contain at least one row"
        )
    return frozen


def _require_nonblank_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ChallengePackError(
            f"challenge.toml field {field_name!r} must be a non-empty string"
        )
    return value.strip()


def _resolve_challenge_id(raw_id: Any, code: str) -> UUID:
    if raw_id is None:
        return uuid5(NAMESPACE_DNS, f"data-pipeline-tycoon.challenge.{code}")
    if not isinstance(raw_id, str):
        raise ChallengePackError("challenge.toml field 'id' must be a UUID string")
    try:
        return UUID(raw_id)
    except ValueError as exc:
        raise ChallengePackError(f"Invalid UUID {raw_id!r} in challenge.toml") from exc


def _parse_difficulty(raw_value: Any) -> Difficulty:
    if isinstance(raw_value, bool):
        raise ChallengePackError("challenge.toml field 'difficulty' cannot be a bool")
    if isinstance(raw_value, int):
        try:
            return Difficulty(raw_value)
        except ValueError as exc:
            raise ChallengePackError(
                f"difficulty must be 1, 2 or 3 (got {raw_value})"
            ) from exc
    if isinstance(raw_value, str):
        mapped = _DIFFICULTY_NAMES.get(raw_value.strip().upper())
        if mapped is not None:
            return mapped
    raise ChallengePackError(
        "challenge.toml field 'difficulty' must be 1, 2 or 3 (or EASY/MEDIUM/HARD)"
    )


def _parse_max_seconds(raw_value: Any) -> float:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        raise ChallengePackError("challenge.toml field 'max_seconds' must be a number")
    val = float(raw_value)
    if not math.isfinite(val) or val <= 0:
        raise ChallengePackError("challenge.toml field 'max_seconds' must be > 0")
    return val


def _parse_hints(raw_value: Any) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list) or not all(
        isinstance(item, str) and item.strip() for item in raw_value
    ):
        raise ChallengePackError(
            "challenge.toml field 'hints' must be a list of non-empty strings"
        )
    return tuple(item.strip() for item in raw_value)


def _parse_starter_sql(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ChallengePackError(
            "challenge.toml field 'starter_sql' must be a non-empty string"
        )
    return raw_value.strip()
