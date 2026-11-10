"""Proton Bridge's keeping: `proton_bridge`, one row holding the sealed vault and keychain, the `generation` raised on
each write-back, the `epoch` raised each time a holder starts a new Bridge pod, the site and pod the epoch belongs to,
the hash of the token its keeper uses, and the keeper's last sign of life; and `proton_bridge_accounts`, a row per
Proton account Bridge holds, each the connection it is, with its state and the epoch its sync last finished in."""

from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE proton_bridge (
            id smallint PRIMARY KEY CHECK (id = 1),
            epoch bigint NOT NULL DEFAULT 0 CHECK (epoch >= 0),
            generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
            vault bytea,
            keychain bytea,
            site text,
            pod text,
            token_sha256 bytea CHECK (length(token_sha256) = 32),
            started_at timestamptz,
            heartbeat_at timestamptz,
            certificate_sha256 text
        );
        INSERT INTO proton_bridge (id) VALUES (1);

        CREATE TABLE proton_bridge_accounts (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id),
            connection_id bigint NOT NULL UNIQUE REFERENCES connections (id) ON DELETE CASCADE,
            proton_user_id text NOT NULL UNIQUE CHECK (proton_user_id ~ '\S'),
            state text NOT NULL CHECK (state IN ('connected', 'signed_out', 'locked')),
            addresses text[] NOT NULL DEFAULT '{}',
            synced_epoch bigint NOT NULL DEFAULT 0,
            sync_progress double precision CHECK (sync_progress BETWEEN 0 AND 1)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE proton_bridge_accounts; DROP TABLE proton_bridge;")
