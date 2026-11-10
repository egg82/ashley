"""A household's connections to services outside her, one per kind: the base URL and the secret sealed under the app's
key (`ashley.connections.sealing`), who added it and when the service last answered with it."""

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE connections (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            kind text NOT NULL CHECK (kind IN ('sure')),
            base_url text NOT NULL,
            secret bytea NOT NULL,
            added_by bigint REFERENCES people (id) ON DELETE SET NULL,
            added_at timestamptz NOT NULL DEFAULT now(),
            checked_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (household_id, kind)
        );
        """
    )
