"""A fact can be standing: it reaches every reply, not only those whose words match it. `diet` joins the kinds."""

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE facts
            ADD COLUMN standing boolean NOT NULL DEFAULT false,
            DROP CONSTRAINT facts_kind_check,
            ADD CONSTRAINT facts_kind_check
                CHECK (kind IN ('preference', 'routine', 'plan', 'person', 'health', 'diet', 'home', 'other'));
        """
    )
