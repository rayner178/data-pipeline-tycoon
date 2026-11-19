"""Idempotent seed for the three MVP challenges."""

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
            "La tabla staging_customers (customer_id, full_name, email, updated_at) "
            "tiene registros repetidos por cliente. Devuelve exactamente una fila por "
            "cliente con su versión más reciente (mayor updated_at): columnas "
            "customer_id, full_name, email."
        ),
        difficulty=Difficulty.EASY,
        setup_sql=(
            "CREATE TABLE staging_customers (\n"
            "    customer_id INT NOT NULL,\n"
            "    full_name TEXT NOT NULL,\n"
            "    email TEXT,\n"
            "    updated_at DATE NOT NULL\n"
            ");\n"
            "INSERT INTO staging_customers "
            "(customer_id, full_name, email, updated_at) VALUES\n"
            "    (1, 'Ana Pérez', 'ana.old@example.com', '2026-01-10'),\n"
            "    (1, 'Ana Pérez', 'ana@example.com', '2026-02-15'),\n"
            "    (2, 'Luis Gómez', 'luis@example.com', '2026-01-20'),\n"
            "    (2, 'Luis Gómez', 'luis.dup@example.com', '2026-01-05'),\n"
            "    (3, 'Marta Díaz', NULL, '2026-03-01');"
        ),
        expected_result=(
            (1, "Ana Pérez", "ana@example.com"),
            (2, "Luis Gómez", "luis@example.com"),
            (3, "Marta Díaz", None),
        ),
        max_seconds=2.0,
        ordered=False,
    ),
    Challenge(
        id=UUID("00000000-0000-0000-0000-000000000102"),
        code="fix-multiplying-join",
        module="postgresql",
        title="Corregir un JOIN que multiplica filas",
        description=(
            "Al unir customers (id, name), orders (id, customer_id, total_amount) y "
            "payments (id, order_id, paid_amount), el pedido 10 tiene dos pagos "
            "parciales y duplica su total_amount. Devuelve por cada cliente: "
            "customer_id, name, total_ordered y total_paid sin multiplicar filas."
        ),
        difficulty=Difficulty.MEDIUM,
        setup_sql=(
            "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT NOT NULL);\n"
            "CREATE TABLE orders (\n"
            "    id INT PRIMARY KEY,\n"
            "    customer_id INT NOT NULL REFERENCES customers(id),\n"
            "    total_amount NUMERIC(10, 2) NOT NULL\n"
            ");\n"
            "CREATE TABLE payments (\n"
            "    id INT PRIMARY KEY,\n"
            "    order_id INT NOT NULL REFERENCES orders(id),\n"
            "    paid_amount NUMERIC(10, 2) NOT NULL\n"
            ");\n"
            "INSERT INTO customers (id, name) VALUES\n"
            "    (1, 'Comercial Norte'),\n"
            "    (2, 'Distribuidora Sur');\n"
            "INSERT INTO orders (id, customer_id, total_amount) VALUES\n"
            "    (10, 1, 100.00),\n"
            "    (11, 1, 50.00),\n"
            "    (12, 2, 85.50);\n"
            "INSERT INTO payments (id, order_id, paid_amount) VALUES\n"
            "    (100, 10, 60.00),\n"
            "    (101, 10, 40.00),\n"
            "    (102, 11, 50.00),\n"
            "    (103, 12, 85.50);"
        ),
        expected_result=(
            (1, "Comercial Norte", Decimal("150.00"), Decimal("150.00")),
            (2, "Distribuidora Sur", Decimal("85.50"), Decimal("85.50")),
        ),
        max_seconds=2.0,
        ordered=False,
    ),
    Challenge(
        id=UUID("00000000-0000-0000-0000-000000000103"),
        code="index-slow-query",
        module="postgresql",
        title="Acelerar una consulta lenta aprovechando el índice",
        description=(
            "La tabla events (id, user_id, created_at, kind) tiene 5,000 filas y el "
            "índice idx_events_user_created ON events (user_id, created_at). "
            "Consulta id, kind, created_at del usuario 42 desde '2026-08-01' "
            "(inclusive), ordenados por created_at ASC, id ASC, de modo que "
            "PostgreSQL utilice el índice."
        ),
        difficulty=Difficulty.HARD,
        setup_sql=(
            "CREATE TABLE events (\n"
            "    id INT PRIMARY KEY,\n"
            "    user_id INT NOT NULL,\n"
            "    created_at DATE NOT NULL,\n"
            "    kind TEXT NOT NULL\n"
            ");\n"
            "INSERT INTO events (id, user_id, created_at, kind)\n"
            "SELECT\n"
            "    g,\n"
            "    (g % 250) + 1,\n"
            "    (DATE '2026-01-01' + ((g % 360) * INTERVAL '1 day'))::date,\n"
            "    CASE WHEN g % 3 = 0 THEN 'purchase' "
            "WHEN g % 2 = 0 THEN 'click' ELSE 'login' END\n"
            "FROM generate_series(1, 5000) AS g;\n"
            "CREATE INDEX idx_events_user_created ON events (user_id, created_at);\n"
            "ANALYZE events;"
        ),
        expected_result=(
            (4541, "login", "2026-08-10"),
            (2041, "login", "2026-08-30"),
            (2791, "login", "2026-09-29"),
            (291, "purchase", "2026-10-19"),
            (3541, "login", "2026-10-29"),
            (1041, "purchase", "2026-11-18"),
            (4291, "login", "2026-11-28"),
            (1791, "purchase", "2026-12-18"),
        ),
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
