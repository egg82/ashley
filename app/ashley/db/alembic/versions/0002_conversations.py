"""People, conversations, their participants and turns. Each row carries household_id, and every reference between
them includes it, so a person can take part in or speak in only their own household's conversations."""

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE people (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id),
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, household_id)
        );

        CREATE TABLE conversations (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id),
            kind text NOT NULL CHECK (kind IN ('command', 'chat', 'brainstorm')),
            started_at timestamptz NOT NULL DEFAULT now(),
            last_activity_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, household_id)
        );

        CREATE TABLE conversation_participants (
            conversation_id bigint NOT NULL,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            PRIMARY KEY (conversation_id, person_id),
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id)
        );

        CREATE TABLE turns (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            conversation_id bigint NOT NULL,
            household_id bigint NOT NULL,
            author text NOT NULL CHECK (author IN ('person', 'ashley')),
            speaker_id bigint,
            text text NOT NULL CHECK (text ~ '\S'),
            at timestamptz NOT NULL DEFAULT now(),
            CHECK (author = 'person' OR speaker_id IS NULL),
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id),
            FOREIGN KEY (speaker_id, household_id) REFERENCES people (id, household_id)
        );

        CREATE INDEX turns_by_conversation ON turns (conversation_id, id);
        CREATE INDEX conversation_participants_by_person ON conversation_participants (person_id);
        """
    )
