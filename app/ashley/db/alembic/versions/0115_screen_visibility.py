"""An open screen names itself (`live_screens.token`, made by the page at load) and says whether it is in the
foreground (`visible`, NULL until it has reported), so a pod on either site can tell which screens are being looked at. The
index serves the household-wide prune and listing."""

from alembic import op

revision: str = "0115"
down_revision: str | None = "0114"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE live_screens ADD COLUMN token uuid, ADD COLUMN visible boolean;
        CREATE INDEX live_screens_household ON live_screens (household_id, seen_at);
        """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX live_screens_household;
        ALTER TABLE live_screens DROP COLUMN token, DROP COLUMN visible;
        """)
