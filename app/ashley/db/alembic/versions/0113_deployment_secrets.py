"""The deployment's own secrets (`ashley.connections.deployment_secrets`): one row per name, its value sealed under the
connections key. Written once, by whichever pod settles it first, and never updated."""

from alembic import op

revision: str = "0113"
down_revision: str | None = "0112"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE deployment_secrets (
            name text PRIMARY KEY CHECK (name ~ '^[a-z][a-z_]*$'),
            sealed bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """)


def downgrade() -> None:
    op.execute("DROP TABLE deployment_secrets")
