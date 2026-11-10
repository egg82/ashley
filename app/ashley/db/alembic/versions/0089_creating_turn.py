"""A reminder or watch a tainted turn made keeps that turn (its conversation and id), so the turn it wakes can be judged
by what the person said there. Rows made earlier have none."""

from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"


def upgrade() -> None:
    for table in ("wakes", "watches"):
        op.execute(f"""
            ALTER TABLE {table} ADD COLUMN made_conversation_id bigint, ADD COLUMN made_turn_id bigint,
                ADD CONSTRAINT {table}_made_in_both CHECK ((made_conversation_id IS NULL) = (made_turn_id IS NULL))""")


def downgrade() -> None:
    for table in ("wakes", "watches"):
        op.execute(f"""
            ALTER TABLE {table} DROP CONSTRAINT {table}_made_in_both, DROP COLUMN made_turn_id,
                DROP COLUMN made_conversation_id""")
