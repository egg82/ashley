"""A camera's detector event she speaks on is a wake of its own kind (`detection`): the camera and the recordings known
when it was heard ride in `changes`, its class in `event`, and it names no person and no device."""

from alembic import op

revision: str = "0134"
down_revision: str | None = "0133"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wakes
            DROP CONSTRAINT wakes_kind_check,
            ADD CONSTRAINT wakes_kind_check CHECK (kind IN ('house', 'reminder', 'watch', 'detection')),
            ADD CONSTRAINT wakes_detection_fields CHECK (kind <> 'detection' OR (changes ? 'camera'
                AND person_id IS NULL AND device_id IS NULL AND who IS NULL AND what IS NULL))""")


def downgrade() -> None:
    op.execute("DELETE FROM wakes WHERE kind = 'detection'")
    op.execute("""
        ALTER TABLE wakes
            DROP CONSTRAINT wakes_detection_fields,
            DROP CONSTRAINT wakes_kind_check,
            ADD CONSTRAINT wakes_kind_check CHECK (kind IN ('house', 'reminder', 'watch'))""")
