"""A reminder, a watch and a bench piece made in a turn that had read outside words carry that taint (`taint`, the origin
or the tool that tainted the turn; `outside`, set on a piece), so a later turn that reads what they hold is tainted too."""

from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wakes ADD COLUMN taint text;
        ALTER TABLE watches ADD COLUMN taint text;
        ALTER TABLE bench_pieces ADD COLUMN outside boolean NOT NULL DEFAULT false""")


def downgrade() -> None:
    op.execute("ALTER TABLE bench_pieces DROP COLUMN outside; ALTER TABLE watches DROP COLUMN taint; "
               "ALTER TABLE wakes DROP COLUMN taint")
