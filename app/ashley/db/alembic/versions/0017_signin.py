"""Sign-in through authentik: the sign-ins in flight, the sessions they open, and the authentik accounts refused for
want of a mapping, kept so the admin can map them. A session hangs off the account it signed in with, so removing the
account ends its sessions. A sign-in in flight and a refused account belong to no household yet. Tokens and
states are stored only as their SHA-256."""

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE signin_pending (
            state_sha256 bytea PRIMARY KEY CHECK (length(state_sha256) = 32),
            verifier text NOT NULL CHECK (verifier ~ '\S'),
            nonce text NOT NULL CHECK (nonce ~ '\S'),
            next text NOT NULL CHECK (next ~ '^/'),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE UNIQUE INDEX accounts_id_household ON accounts (id, household_id);

        CREATE TABLE sessions (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            token_sha256 bytea NOT NULL UNIQUE CHECK (length(token_sha256) = 32),
            account_id bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            FOREIGN KEY (account_id, household_id) REFERENCES accounts (id, household_id) ON DELETE CASCADE
        );

        CREATE INDEX sessions_by_account ON sessions (account_id);
        CREATE INDEX sessions_by_expiry ON sessions (expires_at);

        CREATE TABLE signin_unmapped (
            system text NOT NULL CHECK (system ~ '^[a-z][a-z0-9_]*$'),
            external_id text NOT NULL CHECK (external_id ~ '\S'),
            username text NOT NULL,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (system, external_id)
        );
        """
    )
