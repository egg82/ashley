"""The household's own pronunciation words (`household_lexicon`, one row per household and real spelling), not a shipped
file: a household starts with none."""

from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE household_lexicon (
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            real text NOT NULL,
            spoken text NOT NULL,
            updated_at timestamptz NOT NULL,
            updated_by bigint,
            PRIMARY KEY (household_id, real)
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE household_lexicon")
