"""A person's agreeing turn keeps what became of the held calls it carried out (`turns.agreed`, only a person's), shown
beside it in place of a turn of hers."""

from alembic import op

revision: str = "0096"
down_revision: str | None = "0095"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE turns ADD COLUMN agreed jsonb,
            ADD CONSTRAINT turns_agreed_persons CHECK (agreed IS NULL OR author = 'person')""")


def downgrade() -> None:
    op.execute("ALTER TABLE turns DROP CONSTRAINT turns_agreed_persons, DROP COLUMN agreed")
