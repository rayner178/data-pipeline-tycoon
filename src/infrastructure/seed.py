"""Idempotent seed for the three MVP challenges (placeholder data until phase 5)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from domain.entities import Challenge, Difficulty
from infrastructure.db import create_db_engine
from infrastructure.repositories import SqlAlchemyChallengeRepository

MVP_CHALLENGES: tuple[Challenge, ...] = (
    Challenge(
        id=UUID("00000000-0000-0000-0000-000000000101"),
        code="dedupe-row-number",
        module="postgresql",
        title="Eliminar duplicados con ROW_NUMBER()",
        description=(
            "La tabla staging_customers tiene registros repetidos. "
            "Devuelve el registro más reciente de cada cliente usando ROW_NUMBER()."
        ),
        difficulty=Difficulty.EASY,
        setup_sql=(
            "CREATE TABLE staging_customers ("
            "customer_id INT, name TEXT, updated_at INT);"
        ),
        expected_result=((1, "Ana"), (2, "Luis")),
        max_seconds=2.0,
        ordered=False,
    ),
    Challenge(
        id=UUID("00000000-0000-0000-0000-000000000102"),
        code="fix-multiplying-join",
        module="postgresql",
        title="Corregir un JOIN que multiplica filas",
        description=(
            "La consulta actual duplica los totales al unir pedidos con pagos. "
            "Agrega o corrige el JOIN para devolver el total exacto por cliente."
        ),
        difficulty=Difficulty.MEDIUM,
        setup_sql=(
            "CREATE TABLE orders (id INT, customer_id INT, amount NUMERIC(10, 2));"
        ),
        expected_result=(
            (1, Decimal("150.00")),
            (2, Decimal("85.50")),
        ),
        max_seconds=2.0,
        ordered=False,
    ),
    Challenge(
        id=UUID("00000000-0000-0000-0000-000000000103"),
        code="index-slow-query",
        module="postgresql",
        title="Acelerar una consulta lenta con un índice",
        description=(
            "Crea el índice adecuado sobre la tabla de eventos y ejecuta la consulta "
            "para filtrar por usuario y rango de fechas sin hacer un Seq Scan."
        ),
        difficulty=Difficulty.HARD,
        setup_sql=(
            "CREATE TABLE events (id INT, user_id INT, created_at INT, kind TEXT);"
        ),
        expected_result=((1, "login"), (2, "query")),
        max_seconds=2.0,
        ordered=True,
    ),
)


def seed_mvp_challenges(session: Session) -> list[Challenge]:
    """Insert or update the 3 MVP challenges idempotently."""
    repository = SqlAlchemyChallengeRepository(session)
    for challenge in MVP_CHALLENGES:
        repository.upsert(challenge)
    session.commit()
    return list(MVP_CHALLENGES)


def main() -> None:
    engine = create_db_engine()
    try:
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as session:
            seed_mvp_challenges(session)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
