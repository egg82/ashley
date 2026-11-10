"""Memory: one row per fact, current while `valid_to` is null; a correction closes the row and points it at the fact
that replaced it. Every reference includes household_id, so a fact can name only its own household's people,
conversations and facts. No reference cascades: deleting a person or a conversation must decide what happens to the
facts, and a `Forget` that left any fact it superseded behind fails instead of keeping it as history."""

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE facts (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id),
            about_id bigint,
            owner_id bigint,
            visibility text NOT NULL CHECK (visibility IN ('shared', 'discreet', 'private')),
            visibility_stated boolean NOT NULL,
            kind text NOT NULL CHECK (kind IN ('preference', 'routine', 'plan', 'person', 'health', 'home', 'other')),
            text text NOT NULL CHECK (text ~ '\S'),
            source_conversation_id bigint NOT NULL,
            valid_from timestamptz NOT NULL,
            valid_to timestamptz,
            superseded_by bigint,
            search tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
            UNIQUE (id, household_id),
            CHECK (superseded_by IS NULL OR valid_to IS NOT NULL),
            FOREIGN KEY (about_id, household_id) REFERENCES people (id, household_id),
            FOREIGN KEY (owner_id, household_id) REFERENCES people (id, household_id),
            FOREIGN KEY (source_conversation_id, household_id) REFERENCES conversations (id, household_id),
            FOREIGN KEY (superseded_by, household_id) REFERENCES facts (id, household_id)
        );

        CREATE INDEX facts_current_by_household ON facts (household_id) WHERE valid_to IS NULL;
        CREATE INDEX facts_search ON facts USING gin (search);
        CREATE INDEX facts_by_successor ON facts (superseded_by) WHERE superseded_by IS NOT NULL;
        """
    )
