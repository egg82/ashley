"""A watch's brief, whether it is standing, and the labels agreed with it (`ashley.watches`): `standing_s` is how far
each successful read moves a standing watch's expiry, null for one that is not standing."""

from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE watches
            ADD COLUMN brief text CHECK (length(brief) BETWEEN 1 AND 500),
            ADD COLUMN standing_s double precision CHECK (standing_s > 0),
            ADD COLUMN grant_labels text[] NOT NULL DEFAULT '{}' CHECK (cardinality(grant_labels) <= 20)""")


def downgrade() -> None:
    op.execute("ALTER TABLE watches DROP COLUMN brief, DROP COLUMN standing_s, DROP COLUMN grant_labels")
