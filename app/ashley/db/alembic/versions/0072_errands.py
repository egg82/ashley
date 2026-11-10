"""Errands: asks she could not carry out for want of a tool source, held until it answers (`ashley.errands`)."""

from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE errands (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            asker_id bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL UNIQUE,
            source text NOT NULL CHECK (source ~ '\\S'),
            state text NOT NULL DEFAULT 'due' CHECK (state IN ('due', 'running', 'done', 'given_up')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            reason text CHECK (reason IN ('attempts', 'expired', 'interrupted', 'refused')),
            created_at timestamptz NOT NULL DEFAULT now(),
            claimed_at timestamptz,
            finished_at timestamptz,
            result text,
            visibility text NOT NULL CHECK (visibility IN ('shared', 'private')),
            told_at timestamptz,
            CHECK ((state = 'given_up') = (reason IS NOT NULL)),
            CHECK ((state = 'done') = (result IS NOT NULL)),
            CHECK (told_at IS NULL OR state = 'done'),
            FOREIGN KEY (asker_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id)
                ON DELETE CASCADE,
            FOREIGN KEY (turn_id, conversation_id) REFERENCES turns (id, conversation_id) ON DELETE CASCADE
        )""")
    op.execute("CREATE INDEX errands_due ON errands (created_at) WHERE state = 'due'")
    op.execute("CREATE INDEX errands_untold ON errands (household_id, asker_id) WHERE state = 'done' AND told_at IS NULL")


def downgrade() -> None:
    op.execute("DROP TABLE errands")
