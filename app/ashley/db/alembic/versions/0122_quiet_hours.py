"""A person's own quiet hours (`ashley.people.model.QuietHours`): a daily window of whole hours in a zone of their
choosing, all three set or none. While it holds, nothing she says on her own initiative reaches them."""

from alembic import op

revision: str = "0122"
down_revision: str | None = "0121"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE people
            ADD COLUMN quiet_from smallint CHECK (quiet_from BETWEEN 0 AND 23),
            ADD COLUMN quiet_to smallint CHECK (quiet_to BETWEEN 0 AND 23),
            ADD COLUMN quiet_timezone text,
            ADD CONSTRAINT people_quiet_whole CHECK (
                (quiet_from IS NULL AND quiet_to IS NULL AND quiet_timezone IS NULL)
                OR (quiet_from IS NOT NULL AND quiet_to IS NOT NULL AND quiet_timezone IS NOT NULL
                    AND quiet_from <> quiet_to))
        """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE people DROP CONSTRAINT people_quiet_whole,
            DROP COLUMN quiet_from, DROP COLUMN quiet_to, DROP COLUMN quiet_timezone
        """)
