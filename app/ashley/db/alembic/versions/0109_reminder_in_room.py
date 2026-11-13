"""A reminder's words may be said in a room (`route` `room`, through a satellite) or shown on a screen (`screen`, the
kiosk), the device named by `route_device_id`; a device removed leaves it NULL and the reminder goes to the phone. A
device's open screen is recorded beside a person's (`live_screens.device_id`), so either site can tell whether the
kiosk is showing."""

from alembic import op

revision: str = "0109"
down_revision: str | None = "0108"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wakes DROP CONSTRAINT wakes_route_check;
        ALTER TABLE wakes
            ADD CONSTRAINT wakes_route_check CHECK (route IN ('phone', 'quiet', 'room', 'screen')),
            ADD COLUMN route_device_id bigint REFERENCES devices (id) ON DELETE SET NULL,
            ADD CONSTRAINT wakes_route_device_routed CHECK (route_device_id IS NULL OR route IN ('room', 'screen'));
        ALTER TABLE live_screens
            ALTER COLUMN person_id DROP NOT NULL,
            ADD COLUMN device_id bigint REFERENCES devices (id) ON DELETE CASCADE,
            ADD CONSTRAINT live_screens_person_or_device CHECK (num_nonnulls(person_id, device_id) = 1);
        CREATE INDEX live_screens_device ON live_screens (device_id, seen_at) WHERE device_id IS NOT NULL;
        """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM live_screens WHERE device_id IS NOT NULL;
        ALTER TABLE live_screens DROP COLUMN device_id, ALTER COLUMN person_id SET NOT NULL;
        UPDATE wakes SET route = 'phone' WHERE route IN ('room', 'screen');
        ALTER TABLE wakes DROP COLUMN route_device_id, DROP CONSTRAINT wakes_route_check;
        ALTER TABLE wakes ADD CONSTRAINT wakes_route_check CHECK (route IN ('phone', 'quiet'));
        """)
