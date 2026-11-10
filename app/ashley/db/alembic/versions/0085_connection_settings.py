"""What a person sets on a connection (`connection_settings`, one row per connection, replaced whole under a version) and
the log of each key a write changed (`connection_settings_log`, kept 400 days by the code that writes it).

Home Assistant's household-specific lists live here, not in shipped files: a household starts with nothing, which is
the least trust."""

from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE connection_settings (
            connection_id bigint PRIMARY KEY REFERENCES connections (id) ON DELETE CASCADE,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            values jsonb NOT NULL,
            version integer NOT NULL CHECK (version >= 1),
            updated_at timestamptz NOT NULL,
            updated_by bigint
        );

        CREATE TABLE connection_settings_log (
            id bigserial PRIMARY KEY,
            connection_id bigint NOT NULL,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            changed_by bigint,
            changed_at timestamptz NOT NULL DEFAULT now(),
            key text NOT NULL,
            before jsonb,
            after jsonb
        );
        CREATE INDEX connection_settings_log_of ON connection_settings_log (connection_id, id DESC);
        CREATE INDEX connection_settings_log_age ON connection_settings_log (changed_at)""")


def downgrade() -> None:
    op.execute("DROP TABLE connection_settings_log; DROP TABLE connection_settings")
