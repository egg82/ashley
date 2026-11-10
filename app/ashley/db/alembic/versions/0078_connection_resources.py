"""What a connection reaches, as its service names it: `connection_resources`, a row per resource (a mailbox, named by
its address), shared with the household or kept by the connection's owner, on the connection's own household. Holding stays the connection's
(`connections.person_id`); a kind's `holders` replaced its `personal` flag in the application, which already enforces
who may hold a kind, so the table needs no check for it."""

from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE connections ADD UNIQUE (id, household_id);

        CREATE TABLE connection_resources (
            household_id bigint NOT NULL,
            connection_id bigint NOT NULL,
            ref text NOT NULL CHECK (length(ref) BETWEEN 1 AND 200),
            kind text NOT NULL CHECK (kind IN ('mailbox')),
            name text NOT NULL,
            shared boolean NOT NULL,
            UNIQUE (connection_id, ref),
            FOREIGN KEY (connection_id, household_id) REFERENCES connections (id, household_id) ON DELETE CASCADE
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE connection_resources; ALTER TABLE connections DROP CONSTRAINT connections_id_household_id_key;")
