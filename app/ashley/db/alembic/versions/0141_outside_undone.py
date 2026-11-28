"""An Undo taken is kept on the action it took back (`ashley.senses.outside_record`): `outside_actions` gains when it
was undone (`undone_at`), by whom (`undone_by`) and how it stands (`undone_how`): `undoing` while a route is carrying it
out, `undone`, `waiting_on_you` (a delete proposed for the person's yes) or `gone` (its target was no longer there). All
three are null on a row never undone, and only a row with an undo can have them."""

from alembic import op

revision: str = "0141"
down_revision: str | None = "0140"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE outside_actions
            ADD COLUMN undone_at timestamptz,
            ADD COLUMN undone_by bigint,
            ADD COLUMN undone_how text,
            ADD CONSTRAINT outside_actions_undone_whole CHECK (
                (undone_at IS NULL) = (undone_how IS NULL) AND (undone_at IS NULL) = (undone_by IS NULL)),
            ADD CONSTRAINT outside_actions_undone_how CHECK (
                undone_how IN ('undoing', 'undone', 'waiting_on_you', 'gone')),
            ADD CONSTRAINT outside_actions_undone_has_undo CHECK (undone_at IS NULL OR undo_kind IS NOT NULL)""")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE outside_actions
            DROP CONSTRAINT outside_actions_undone_has_undo,
            DROP CONSTRAINT outside_actions_undone_how,
            DROP CONSTRAINT outside_actions_undone_whole,
            DROP COLUMN undone_how,
            DROP COLUMN undone_by,
            DROP COLUMN undone_at""")
