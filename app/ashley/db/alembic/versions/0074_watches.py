"""Watches: reads she repeats until a condition or a time (`ashley.watches`), and the `watch` wakes a check stores."""

from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE watches (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            kind text NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]{0,63}$'),
            target text NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
            label text NOT NULL CHECK (length(label) BETWEEN 1 AND 100),
            bench_id bigint,
            armed_by text NOT NULL CHECK (armed_by IN ('ashley', 'handoff')),
            track text[] NOT NULL CHECK (cardinality(track) BETWEEN 1 AND 8),
            when_clauses jsonb NOT NULL CHECK (jsonb_typeof(when_clauses) = 'array'),
            until_clauses jsonb CHECK (jsonb_typeof(until_clauses) = 'array'),
            tools text[],
            interval_s double precision NOT NULL CHECK (interval_s > 0),
            expires_at timestamptz NOT NULL,
            state text NOT NULL DEFAULT 'armed' CHECK (state IN ('armed', 'paused', 'ended')),
            reason text,
            failures integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
            version integer NOT NULL DEFAULT 0 CHECK (version >= 0),
            series integer NOT NULL DEFAULT 0 CHECK (series >= 0),
            baseline jsonb CHECK (jsonb_typeof(baseline) = 'object'),
            next_check_at timestamptz NOT NULL DEFAULT now(),
            armed_at timestamptz NOT NULL DEFAULT now(),
            last_woke_at timestamptz,
            ended_at timestamptz,
            CHECK ((reason IS NULL) = (state = 'armed')),
            CHECK (state <> 'ended' OR reason IN ('until', 'expired', 'disarmed')),
            CHECK (state <> 'paused' OR reason IN ('unreachable', 'not_connected', 'refused', 'bad_result',
                                                   'too_many_items', 'unknown_kind')),
            CHECK ((state = 'ended') = (ended_at IS NOT NULL)),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        )""")
    op.execute("CREATE UNIQUE INDEX watches_live ON watches (person_id, kind, target) WHERE state <> 'ended'")
    op.execute("CREATE INDEX watches_next_check ON watches (next_check_at) WHERE state <> 'ended'")
    op.execute("""
        ALTER TABLE wakes
            DROP CONSTRAINT wakes_kind_check,
            ADD CONSTRAINT wakes_kind_check CHECK (kind IN ('house', 'reminder', 'watch')),
            ADD COLUMN watch_id bigint REFERENCES watches (id) ON DELETE CASCADE,
            ADD COLUMN changes jsonb CHECK (jsonb_typeof(changes) = 'object'),
            ADD CONSTRAINT wakes_watch_fields CHECK ((kind = 'watch') = (watch_id IS NOT NULL)
                AND (kind <> 'watch' OR (changes IS NOT NULL AND person_id IS NOT NULL AND device_id IS NULL)))""")
    op.execute("CREATE INDEX wakes_watch ON wakes (watch_id) WHERE settled_at IS NULL AND watch_id IS NOT NULL")
    op.execute("ALTER TABLE wakes ALTER CONSTRAINT wakes_person_id_household_id_fkey DEFERRABLE INITIALLY DEFERRED")


def downgrade() -> None:
    op.execute("DELETE FROM wakes WHERE kind = 'watch'")
    op.execute("ALTER TABLE wakes ALTER CONSTRAINT wakes_person_id_household_id_fkey NOT DEFERRABLE")
    op.execute("""
        ALTER TABLE wakes
            DROP CONSTRAINT wakes_watch_fields,
            DROP COLUMN changes,
            DROP COLUMN watch_id,
            DROP CONSTRAINT wakes_kind_check,
            ADD CONSTRAINT wakes_kind_check CHECK (kind IN ('house', 'reminder'))""")
    op.execute("DROP TABLE watches")
