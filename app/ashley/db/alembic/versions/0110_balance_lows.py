"""Whether an armed balance rule's account is below its threshold now (`low`), and how many times it has fallen below
(`episode`), so one fall fires one reminder until the balance recovers (`ashley.senses.deposits.Deposits.below`)."""

from alembic import op

revision: str = "0110"
down_revision: str | None = "0109"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE balance_lows (
            armed_id bigint PRIMARY KEY REFERENCES wakes (id) ON DELETE CASCADE,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            low boolean NOT NULL,
            episode integer NOT NULL CHECK (episode >= 1)
        );
        """)


def downgrade() -> None:
    op.execute("DROP TABLE balance_lows")
