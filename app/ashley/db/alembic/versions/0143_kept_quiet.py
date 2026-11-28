"""What she decided not to say on her own (`kept_quiet`, kept `quiet_keep_s` by the code that writes it): per conversation,
the person it was for (null for a turn addressed to the household), why as one of a fixed set of codes (`why`, never her
words), the initiative score when the decision had one, and the kind and id of what started the turn."""

from alembic import op

revision: str = "0143"
down_revision: str | None = "0142"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE kept_quiet (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            person_id bigint,
            conversation_id bigint NOT NULL,
            at timestamptz NOT NULL,
            why text NOT NULL CHECK (why IN ('quiet_hours', 'not_greeting', 'below_threshold', 'rolled_silent', 'said_none')),
            score double precision,
            cause_kind text,
            cause_id bigint,
            CONSTRAINT kept_quiet_cause_whole CHECK ((cause_kind IS NULL) = (cause_id IS NULL))
        );
        CREATE INDEX kept_quiet_person ON kept_quiet (household_id, person_id, at DESC);
        CREATE INDEX kept_quiet_age ON kept_quiet (at)""")


def downgrade() -> None:
    op.execute("DROP TABLE kept_quiet")
