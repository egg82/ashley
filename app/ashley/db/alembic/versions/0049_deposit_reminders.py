"""A reminder may wait on an event, not a time: its `trigger` is `time` or `event`, and an event reminder carries its
`deposit_rule` (account, minimum amount, payee, as fields), stays unsettled as armed and is never due. Each match
stores an ordinary once reminder beside it. `deposit_reads` is how far the deposit sense has read a household's
Sure, so a new holder of the lease carries on from it."""

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE wakes
            ADD COLUMN trigger text NOT NULL DEFAULT 'time' CHECK (trigger IN ('time', 'event')),
            ADD COLUMN deposit_rule jsonb CHECK (jsonb_typeof(deposit_rule) = 'object'),
            ADD CONSTRAINT wakes_event_fields CHECK ((trigger = 'event') = (deposit_rule IS NOT NULL)
                AND (trigger = 'time' OR (kind = 'reminder' AND repeat IS NULL)));

        DROP INDEX wakes_due;
        CREATE INDEX wakes_due ON wakes (due_at, id) WHERE settled_at IS NULL AND trigger = 'time';
        CREATE INDEX wakes_armed ON wakes (household_id) WHERE settled_at IS NULL AND trigger = 'event';

        CREATE TABLE deposit_reads (
            household_id bigint PRIMARY KEY REFERENCES households (id) ON DELETE CASCADE,
            read_through date NOT NULL
        );
        """
    )
