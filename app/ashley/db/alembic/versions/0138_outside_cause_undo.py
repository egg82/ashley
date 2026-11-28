"""What she did on her own keeps why and how to take it back (`ashley.senses.outside_record`): `outside_actions` gains
the kind and id of what started the turn (`cause_kind`, `cause_id`) and the inverse of the change (`undo_kind`,
`undo_ref`, `undo_within`). Rows kept before stay null in all five: no cause, and no Undo."""

from alembic import op

revision: str = "0138"
down_revision: str | None = "0137"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE outside_actions
            ADD COLUMN cause_kind text,
            ADD COLUMN cause_id bigint,
            ADD COLUMN undo_kind text,
            ADD COLUMN undo_ref text,
            ADD COLUMN undo_within text,
            ADD CONSTRAINT outside_actions_cause_whole CHECK ((cause_kind IS NULL) = (cause_id IS NULL)),
            ADD CONSTRAINT outside_actions_undo_whole CHECK ((undo_kind IS NULL) = (undo_ref IS NULL))""")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE outside_actions
            DROP CONSTRAINT outside_actions_undo_whole,
            DROP CONSTRAINT outside_actions_cause_whole,
            DROP COLUMN undo_within,
            DROP COLUMN undo_ref,
            DROP COLUMN undo_kind,
            DROP COLUMN cause_id,
            DROP COLUMN cause_kind""")
