"""The kinds of connection are the adapters' to declare (`ashley.connections.kinds`), so the table stops listing them:
the check on `kind` and the check that ties a person to the code-host kinds are dropped. The application refuses a write
of a kind nothing registered and a read of a stored row whose kind is gone, and a secret is sealed bound to its kind and
owner, so a row under another kind or owner does not open."""

from alembic import op

revision: str = "0063"
down_revision: str | None = "0061"


def upgrade() -> None:
    op.execute("ALTER TABLE connections DROP CONSTRAINT connections_kind_check")
    op.execute("ALTER TABLE connections DROP CONSTRAINT connections_owner_check")
