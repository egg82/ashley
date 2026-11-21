"""What a person writes about the thing a connection reaches: a herdr connection's machine ("The workstation, in the
office near the workbench"). Empty for one never described."""

from alembic import op

revision: str = "0124"
down_revision: str | None = "0123"


def upgrade() -> None:
    op.execute("ALTER TABLE connections ADD COLUMN description text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE connections DROP COLUMN description")
