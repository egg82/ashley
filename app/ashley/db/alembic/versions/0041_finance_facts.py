"""A fact can be about money: `finance` joins the kinds."""

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE facts
            DROP CONSTRAINT facts_kind_check,
            ADD CONSTRAINT facts_kind_check
                CHECK (kind IN ('preference', 'routine', 'plan', 'person', 'health', 'finance', 'diet', 'home', 'other'));
        """
    )
