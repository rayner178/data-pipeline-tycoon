"""Initial schema for players, challenges and attempts.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("roblox_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("roblox_user_id", name="uq_players_roblox_user_id"),
    )
    op.create_table(
        "challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False),
        sa.Column("setup_sql", sa.Text(), nullable=False),
        sa.Column(
            "expected_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("max_seconds", sa.Double(), nullable=False),
        sa.Column(
            "ordered",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_challenges_code"),
    )
    op.create_index(
        "ix_challenges_difficulty_code",
        "challenges",
        ["difficulty", "code"],
        unique=False,
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_sql", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("execution_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["challenge_id"], ["challenges.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attempts_challenge_id", "attempts", ["challenge_id"], unique=False
    )
    op.create_index("ix_attempts_player_id", "attempts", ["player_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_attempts_player_id", table_name="attempts")
    op.drop_index("ix_attempts_challenge_id", table_name="attempts")
    op.drop_table("attempts")
    op.drop_index("ix_challenges_difficulty_code", table_name="challenges")
    op.drop_table("challenges")
    op.drop_table("players")
