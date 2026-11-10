"""The object store's sweep: `file_orphans` holds the keys the last pass found unreferenced and old enough, so a key is
deleted only when the next pass finds it so again, on whichever pod and site holds the lease then."""

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE file_orphans (
            object_key text PRIMARY KEY,
            first_seen timestamptz NOT NULL DEFAULT now()
        );
        """
    )
