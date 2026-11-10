"""A reminder a deposit fired carries that deposit as fields (`landed`: cents, day, account name, payee), so her turn
on it states them from data."""

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"


def upgrade() -> None:
    op.execute("ALTER TABLE wakes ADD COLUMN landed jsonb CHECK (jsonb_typeof(landed) = 'object')")
