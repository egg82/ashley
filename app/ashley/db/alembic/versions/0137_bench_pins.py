"""A bench piece's pin (`pin_x`, `pin_y`: its top-left on the bench's map) and box (`box_w`, `box_h`), set only by a
person's move; both null until then (`ashley.workshop.model.Place`)."""

from alembic import op

revision: str = "0137"
down_revision: str | None = "0136"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE bench_pieces
            ADD COLUMN pin_x integer,
            ADD COLUMN pin_y integer,
            ADD COLUMN box_w integer CHECK (box_w >= 1),
            ADD COLUMN box_h integer CHECK (box_h >= 1),
            ADD CHECK ((pin_x IS NULL) = (pin_y IS NULL)),
            ADD CHECK ((box_w IS NULL) = (box_h IS NULL))""")


def downgrade() -> None:
    op.execute("ALTER TABLE bench_pieces DROP COLUMN pin_x, DROP COLUMN pin_y, DROP COLUMN box_w, DROP COLUMN box_h")
