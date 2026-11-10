"""Whether a device's conversations are remembered. The device authors it; a conversation copies it when it starts, so
a device changed later does not rewrite what its earlier conversations were."""

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE devices ADD COLUMN remembers boolean NOT NULL DEFAULT true;
        ALTER TABLE conversations ADD COLUMN remembered boolean NOT NULL DEFAULT true;
        """
    )
