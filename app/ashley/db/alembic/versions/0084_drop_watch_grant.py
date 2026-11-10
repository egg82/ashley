"""A sort's labels run without asking by their tier now (`tools.tiers`), so a watch no longer carries a grant of them."""

from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"


def upgrade() -> None:
    op.execute("ALTER TABLE watches DROP COLUMN grant_labels")


def downgrade() -> None:
    op.execute("ALTER TABLE watches ADD COLUMN grant_labels text[] NOT NULL DEFAULT '{}' "
               "CHECK (cardinality(grant_labels) <= 20)")
