"""A connection has a label its owner gives it, and an owner may hold several of a kind under different labels: the
unique index on (household, kind, owner) takes the label too. Every row that exists keeps the empty label, so no secret
or address is rewritten."""

from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"


def upgrade() -> None:
    op.execute("ALTER TABLE connections ADD COLUMN label text NOT NULL DEFAULT ''")
    op.execute("DROP INDEX connections_owner_key")
    op.execute("CREATE UNIQUE INDEX connections_owner_key ON connections "
               "(household_id, kind, COALESCE(person_id, 0), label)")
