"""Validation and PostgreSQL sandbox tests for declarative ``challenges/`` packs."""

import json
import re
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from application.use_cases.submit_solution import (
    MESSAGE_INDEX_NOT_USED,
    MESSAGE_SOLVED,
    SubmitSolution,
)
from infrastructure.challenge_loader import (
    DEFAULT_CHALLENGES_DIR,
    REQUIRED_PACK_FILES,
    ChallengePack,
    ChallengePackError,
    load_all_challenge_packs,
    load_challenge_pack,
)
from infrastructure.repositories import (
    SqlAlchemyAttemptRepository,
    SqlAlchemyChallengeRepository,
    SqlAlchemyPlayerRepository,
)
from infrastructure.sandbox import PostgresSandboxEvaluator
from infrastructure.system import UtcClock, Uuid4Generator
from infrastructure.uow import SqlAlchemyUnitOfWork

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ALL_PACKS = load_all_challenge_packs()


def _create_valid_pack(
    root: Path,
    slug: str = "sample-pack",
    *,
    code: str | None = None,
    toml_override: str | None = None,
) -> Path:
    pack_dir = root / slug
    pack_dir.mkdir(parents=True, exist_ok=True)
    effective_code = code if code is not None else slug
    toml_text = (
        toml_override
        if toml_override is not None
        else (
            f'code = "{effective_code}"\n'
            'module = "postgresql"\n'
            'title = "Sample challenge"\n'
            'description = "Select all rows ordered by id."\n'
            "difficulty = 1\n"
            "max_seconds = 2.0\n"
            "ordered = true\n"
        )
    )
    (pack_dir / "challenge.toml").write_text(toml_text, encoding="utf-8")
    (pack_dir / "setup.sql").write_text(
        "CREATE TABLE t (id INT); INSERT INTO t VALUES (1), (2);",
        encoding="utf-8",
    )
    (pack_dir / "expected_result.json").write_text("[[1], [2]]", encoding="utf-8")
    (pack_dir / "solution.sql").write_text(
        "SELECT id FROM t ORDER BY id;", encoding="utf-8"
    )
    (pack_dir / "wrong_solution.sql").write_text(
        "SELECT id FROM t WHERE id = 1;", encoding="utf-8"
    )
    return pack_dir


def _count_sandbox_schemas(engine: Engine) -> int:
    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.schemata "
                "WHERE schema_name LIKE 'sandbox_%'"
            )
        ).scalar_one()
    return int(count)


# --- Parametrized validation over every pack in challenges/ -----------------


@pytest.mark.parametrize("pack", _ALL_PACKS, ids=lambda p: p.challenge.code)
def test_declarative_pack_metadata_and_invariants(pack: ChallengePack) -> None:
    assert DEFAULT_CHALLENGES_DIR.is_dir()
    assert pack.directory.name == pack.challenge.code
    assert _KEBAB_RE.match(pack.challenge.code)
    assert pack.solution_sql.strip()
    assert pack.wrong_solution_sql.strip()
    assert len(pack.challenge.expected_result) >= 1


@pytest.mark.parametrize("pack", _ALL_PACKS, ids=lambda p: p.challenge.code)
def test_declarative_pack_solutions_against_real_sandbox(
    session_factory: sessionmaker[Session],
    test_engine: Engine,
    pack: ChallengePack,
) -> None:
    with session_factory() as seed_session:
        SqlAlchemyChallengeRepository(seed_session).upsert(pack.challenge)
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
        ok_res = use_case.execute(
            roblox_user_id=901,
            code=pack.challenge.code,
            sql=pack.solution_sql,
        )
        wrong_res = use_case.execute(
            roblox_user_id=902,
            code=pack.challenge.code,
            sql=pack.wrong_solution_sql,
        )

    assert ok_res.passed is True
    assert ok_res.message == MESSAGE_SOLVED
    assert ok_res.execution_ms is not None
    assert wrong_res.passed is False
    if pack.challenge.requires_index_plan():
        assert wrong_res.message == MESSAGE_INDEX_NOT_USED
    assert _count_sandbox_schemas(test_engine) == 0


# --- Negative unit tests for the loader -------------------------------------


def test_loader_derives_deterministic_uuid_when_omitted(tmp_path: Path) -> None:
    pack_dir = _create_valid_pack(tmp_path, "custom-kebab-1")
    pack = load_challenge_pack(pack_dir)

    expected_uuid = uuid5(
        NAMESPACE_DNS, "data-pipeline-tycoon.challenge.custom-kebab-1"
    )
    assert pack.challenge.id == expected_uuid
    assert pack.hints == ()
    assert pack.starter_sql is None


@pytest.mark.parametrize("missing_file", REQUIRED_PACK_FILES)
def test_loader_rejects_missing_required_file(
    tmp_path: Path, missing_file: str
) -> None:
    pack_dir = _create_valid_pack(tmp_path, "missing-file-pack")
    (pack_dir / missing_file).unlink()

    with pytest.raises(ChallengePackError):
        load_challenge_pack(pack_dir)


def test_loader_rejects_invalid_toml(tmp_path: Path) -> None:
    pack_dir = _create_valid_pack(
        tmp_path,
        "broken-toml",
        toml_override='code = "broken-toml"\nnot valid toml = [',
    )

    with pytest.raises(ChallengePackError):
        load_challenge_pack(pack_dir)


def test_loader_rejects_code_mismatch_with_directory(tmp_path: Path) -> None:
    pack_dir = _create_valid_pack(tmp_path, "folder-slug", code="different-slug")

    with pytest.raises(ChallengePackError, match="must match directory name"):
        load_challenge_pack(pack_dir)


@pytest.mark.parametrize(
    "bad_slug",
    ["bad_underscore", "UpperCase", "-leading", "trailing-", "double--dash"],
)
def test_loader_rejects_non_kebab_case_code(tmp_path: Path, bad_slug: str) -> None:
    pack_dir = _create_valid_pack(tmp_path, bad_slug)

    with pytest.raises(ChallengePackError, match="kebab-case"):
        load_challenge_pack(pack_dir)


def test_loader_rejects_unknown_keys_and_bool_numbers(tmp_path: Path) -> None:
    unknown_key_pack = _create_valid_pack(
        tmp_path,
        "unknown-key",
        toml_override=(
            'code = "unknown-key"\n'
            'module = "postgresql"\n'
            'title = "T"\n'
            'description = "D"\n'
            "difficulty = 1\n"
            "max_seconds = 1.0\n"
            "ordered = false\n"
            'extra_field = "nope"\n'
        ),
    )
    bool_diff_pack = _create_valid_pack(
        tmp_path,
        "bool-diff",
        toml_override=(
            'code = "bool-diff"\n'
            'module = "postgresql"\n'
            'title = "T"\n'
            'description = "D"\n'
            "difficulty = true\n"
            "max_seconds = 1.0\n"
            "ordered = false\n"
        ),
    )

    with pytest.raises(ChallengePackError):
        load_challenge_pack(unknown_key_pack)
    with pytest.raises(ChallengePackError):
        load_challenge_pack(bool_diff_pack)


def test_loader_rejects_invalid_expected_json_empty_sql_and_duplicate_id(
    tmp_path: Path,
) -> None:
    bad_json_pack = _create_valid_pack(tmp_path, "bad-json")
    (bad_json_pack / "expected_result.json").write_text(
        json.dumps([]), encoding="utf-8"
    )
    with pytest.raises(ChallengePackError):
        load_challenge_pack(bad_json_pack)

    blank_sol_pack = _create_valid_pack(tmp_path, "blank-sol")
    (blank_sol_pack / "solution.sql").write_text("   \n", encoding="utf-8")
    with pytest.raises(ChallengePackError):
        load_challenge_pack(blank_sol_pack)

    dup_root = tmp_path / "dup_root"
    same_id = "00000000-0000-0000-0000-000000000999"
    for slug in ("pack-one", "pack-two"):
        _create_valid_pack(
            dup_root,
            slug,
            toml_override=(
                f'id = "{same_id}"\n'
                f'code = "{slug}"\n'
                'module = "postgresql"\n'
                'title = "T"\n'
                'description = "D"\n'
                "difficulty = 1\n"
                "max_seconds = 1.0\n"
                "ordered = false\n"
            ),
        )
    with pytest.raises(ChallengePackError, match="Duplicate challenge UUID"):
        load_all_challenge_packs(dup_root)
