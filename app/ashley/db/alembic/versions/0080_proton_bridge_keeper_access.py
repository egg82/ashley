"""The keeper's token and control-port certificate, sealed, on the Bridge record: the site that does not run Bridge reaches
the keeper with them, the Secret that carries them being in the other cluster."""

from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"


def upgrade() -> None:
    op.execute("ALTER TABLE proton_bridge ADD COLUMN keeper_access bytea;")


def downgrade() -> None:
    op.execute("ALTER TABLE proton_bridge DROP COLUMN keeper_access;")
