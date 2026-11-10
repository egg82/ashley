"""What channels need: a household's timezone and profile, the accounts that name people elsewhere, the devices that
sign in as themselves, and which conversation each thread is carrying. Every row carries household_id, and every
reference includes it."""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE households
            ADD COLUMN timezone text NOT NULL DEFAULT 'UTC',
            ADD COLUMN profile text NOT NULL DEFAULT '';

        CREATE TABLE accounts (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            system text NOT NULL CHECK (system ~ '^[a-z][a-z0-9_]*$'),
            external_id text NOT NULL CHECK (external_id ~ '\S'),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (system, external_id),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id)
        );

        CREATE TABLE devices (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id),
            name text NOT NULL CHECK (name ~ '\S'),
            place text NOT NULL CHECK (place ~ '\S'),
            audience text NOT NULL CHECK (audience IN ('household', 'present')),
            medium text NOT NULL CHECK (medium IN ('spoken', 'text')),
            kind text NOT NULL CHECK (kind IN ('command', 'chat', 'brainstorm')),
            token_sha256 bytea NOT NULL UNIQUE CHECK (length(token_sha256) = 32),
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE conversation_threads (
            thread text PRIMARY KEY CHECK (thread ~ '\S'),
            household_id bigint NOT NULL,
            conversation_id bigint NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id)
        );

        CREATE INDEX accounts_by_household ON accounts (household_id, system);
        """
    )
