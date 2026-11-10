"""Her skills: a household's method documents as append-only versions (a rollback is a new version carrying an older
body), the kinds of work a household has started, the ones it pins so her edits wait for a person, and a bench's kind
of work."""

from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE benches ADD COLUMN work text CHECK (work ~ '\\S');

        CREATE TABLE skill_versions (
            household_id bigint NOT NULL REFERENCES households (id),
            kind text NOT NULL,
            version integer NOT NULL CHECK (version >= 1),
            body text NOT NULL CHECK (body ~ '\\S'),
            what text NOT NULL CHECK (what ~ '\\S'),
            why text NOT NULL CHECK (why ~ '\\S'),
            status text NOT NULL CHECK (status IN ('live', 'proposed', 'declined')),
            base_version integer NOT NULL CHECK (base_version >= 0),
            restored_from integer CHECK (restored_from >= 0),
            bench_id bigint,
            person_id bigint,
            at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (household_id, kind, version),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id)
        );

        CREATE TABLE skill_kinds (
            household_id bigint NOT NULL REFERENCES households (id),
            kind text NOT NULL CHECK (kind ~ '^[a-z0-9][a-z0-9-]*$'),
            label text NOT NULL CHECK (label ~ '\\S'),
            PRIMARY KEY (household_id, kind)
        );

        CREATE TABLE skill_pins (
            household_id bigint NOT NULL REFERENCES households (id),
            kind text NOT NULL,
            PRIMARY KEY (household_id, kind)
        );
        """
    )
