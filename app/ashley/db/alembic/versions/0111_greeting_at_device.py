"""A greeting a house wake's turn makes may be said in a room or shown on a screen, delivered as a reminder is: the
house wake row names the person it is about once routed (`person_id`, which `Wakes.undelivered` hands the phone's
push), beside `route` and `route_device_id`."""

from alembic import op

revision: str = "0111"
down_revision: str | None = "0110"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wakes
            DROP CONSTRAINT wakes_house_fields,
            ADD CONSTRAINT wakes_house_fields CHECK (kind <> 'house' OR (device_id IS NOT NULL
                AND made_by IS NULL AND brief IS NULL AND repeat IS NULL
                AND (person_id IS NULL OR route IN ('room', 'screen'))));
        """)


def downgrade() -> None:
    op.execute("""
        UPDATE wakes SET person_id = NULL, route = 'phone', route_device_id = NULL WHERE kind = 'house';
        ALTER TABLE wakes
            DROP CONSTRAINT wakes_house_fields,
            ADD CONSTRAINT wakes_house_fields CHECK (kind <> 'house' OR (device_id IS NOT NULL AND person_id IS NULL
                AND made_by IS NULL AND brief IS NULL AND repeat IS NULL));
        """)
