"""A watch can carry a standing errand's method (`ashley.watches.model.Arm.method`): the household's skill kind, a slug of
the shape `wakes.method` has (0120), which its woken turn follows."""

from alembic import op

revision: str = "0130"
down_revision: str | None = "0129"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE watches
            ADD COLUMN method text CHECK (method ~ '^[a-z0-9][a-z0-9-]*$' AND length(method) <= 40)""")


def downgrade() -> None:
    op.execute("ALTER TABLE watches DROP COLUMN method")
