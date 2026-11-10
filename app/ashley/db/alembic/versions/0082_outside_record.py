"""What a turn that had read outside words did without asking (`outside_actions`, kept 90 days by the code that writes it),
and the list entities such a turn wrote (`outside_writes`, which `house_ask` treats as outside for a while)."""

from alembic import op

revision: str = "0082"
down_revision: str | None = "0081"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE outside_actions (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            person_id bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL,
            tool text NOT NULL,
            summary text NOT NULL,
            tier text NOT NULL CHECK (tier IN ('runs', 'judged')),
            decision text NOT NULL CHECK (decision = 'run'),
            reason text,
            explanation text,
            at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX outside_actions_turn ON outside_actions (conversation_id, turn_id, id);
        CREATE INDEX outside_actions_age ON outside_actions (at);

        CREATE TABLE outside_writes (
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            entity text NOT NULL,
            at timestamptz NOT NULL,
            PRIMARY KEY (household_id, entity)
        );
        CREATE INDEX outside_writes_age ON outside_writes (at)""")


def downgrade() -> None:
    op.execute("DROP TABLE outside_writes; DROP TABLE outside_actions")
