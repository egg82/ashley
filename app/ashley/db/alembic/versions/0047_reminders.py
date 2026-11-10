"""Reminders are wakes she sets for herself: a wake gains its kind (`house`, handed in by Home Assistant, or
`reminder`), the time it falls due (a house wake's is when it arrived), and a reminder's own fields: whom it is for,
who asked, what to remind them of and how it repeats. A cancelled reminder is settled `cancelled`. A fired reminder
records its push (`delivery`: sending, then delivered or undelivered, with its tries), the firings that could not run
(`fire_attempts`), and when its person dismissed it from their list (`dismissed_at`)."""

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE wakes
            ADD COLUMN kind text NOT NULL DEFAULT 'house' CHECK (kind IN ('house', 'reminder')),
            ADD COLUMN due_at timestamptz,
            ADD COLUMN person_id bigint,
            ADD COLUMN made_by bigint,
            ADD COLUMN brief text CHECK (length(brief) BETWEEN 1 AND 500),
            ADD COLUMN repeat jsonb CHECK (jsonb_typeof(repeat) = 'object'),
            ADD COLUMN fire_attempts integer NOT NULL DEFAULT 0 CHECK (fire_attempts >= 0),
            ADD COLUMN delivery text CHECK (delivery IN ('sending', 'delivered', 'undelivered')),
            ADD COLUMN delivery_attempts integer NOT NULL DEFAULT 0 CHECK (delivery_attempts >= 0),
            ADD COLUMN delivery_tried_at timestamptz,
            ADD COLUMN dismissed_at timestamptz,
            ALTER COLUMN device_id DROP NOT NULL,
            ADD FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id),
            ADD FOREIGN KEY (made_by, household_id) REFERENCES people (id, household_id);

        UPDATE wakes SET due_at = received_at;
        ALTER TABLE wakes ALTER COLUMN due_at SET NOT NULL, ALTER COLUMN due_at SET DEFAULT now();

        ALTER TABLE wakes
            ADD CONSTRAINT wakes_house_fields CHECK (kind <> 'house' OR (device_id IS NOT NULL AND person_id IS NULL
                AND made_by IS NULL AND brief IS NULL AND repeat IS NULL)),
            ADD CONSTRAINT wakes_reminder_fields CHECK (kind <> 'reminder' OR (device_id IS NULL AND who IS NULL
                AND what IS NULL AND person_id IS NOT NULL AND made_by IS NOT NULL AND brief IS NOT NULL)),
            DROP CONSTRAINT wakes_outcome_check,
            ADD CONSTRAINT wakes_outcome_check CHECK (outcome IN ('turn', 'failed', 'no_rule', 'ambiguous',
                'no_person', 'expired', 'cancelled'));

        DROP INDEX wakes_due;
        CREATE INDEX wakes_due ON wakes (due_at, id) WHERE settled_at IS NULL;
        CREATE INDEX wakes_reminders ON wakes (household_id, person_id) WHERE kind = 'reminder' AND dismissed_at IS NULL;
        CREATE INDEX wakes_undelivered ON wakes (settled_at) WHERE delivery IN ('sending', 'undelivered');
        CREATE INDEX wakes_reminders_made ON wakes (household_id, made_by) WHERE kind = 'reminder' AND dismissed_at IS NULL;
        """
    )
