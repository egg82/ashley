"""A connection's secret can come from OAuth: the sealed access token and its expiry beside the refresh token, the
scopes the provider granted, `secret_version` (renewal writes only where it is still the one it read) and `needs`
(set while a person must act before the connection works again). `connect_pending` holds a connect in flight, bound
to the person who started it, with its PKCE verifier sealed and its state stored only as a SHA-256."""

from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE connections
            ADD COLUMN access_token bytea,
            ADD COLUMN access_expires_at timestamptz,
            ADD COLUMN scopes text[] NOT NULL DEFAULT '{}',
            ADD COLUMN secret_version bigint NOT NULL DEFAULT 1,
            ADD COLUMN needs text CHECK (needs IN ('reconnect', 'login'));

        CREATE TABLE connect_pending (
            state_sha256 bytea PRIMARY KEY CHECK (length(state_sha256) = 32),
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            kind text NOT NULL CHECK (kind ~ '\S'),
            label text NOT NULL,
            holder text NOT NULL CHECK (holder IN ('household', 'person')),
            verifier bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE connect_pending;
        ALTER TABLE connections
            DROP COLUMN access_token, DROP COLUMN access_expires_at, DROP COLUMN scopes,
            DROP COLUMN secret_version, DROP COLUMN needs;
        """
    )
