"""Per-device request counts for the API's rate limit: one row per device and fixed window, so every pod on either
site counts in the same place. A row older than the window is deleted by the next request of its device."""

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE device_requests (
            device_id bigint NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
            window_start timestamptz NOT NULL,
            requests integer NOT NULL CHECK (requests > 0),
            PRIMARY KEY (device_id, window_start)
        );
        """
    )
