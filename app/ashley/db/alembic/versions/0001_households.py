"""Households: every row in every later table carries a household_id."""

from alembic import op

revision: str = "0001"
down_revision: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE households (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
