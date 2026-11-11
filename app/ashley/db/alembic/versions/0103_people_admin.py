"""Whether a person is an admin of the deployment: who may change what every household shares (a model provider's key).
A deployment that already has people keeps today's behaviour: every person of its first household (id 1) becomes one,
and an admin revokes the rest from the web."""

from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"


def upgrade() -> None:
    op.execute("ALTER TABLE people ADD COLUMN admin boolean NOT NULL DEFAULT false")
    op.execute("UPDATE people SET admin = true WHERE household_id = 1")


def downgrade() -> None:
    op.execute("ALTER TABLE people DROP COLUMN admin")
