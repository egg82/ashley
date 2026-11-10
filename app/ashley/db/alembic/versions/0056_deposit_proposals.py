"""A money reminder is proposed before it is armed: `deposit_proposals` holds the rule she proposed and the turn it was
proposed in, and arming takes it only from a later turn of the same conversation."""

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE deposit_proposals (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            person_id bigint NOT NULL,
            made_by bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL,
            brief text NOT NULL,
            rule jsonb NOT NULL CHECK (jsonb_typeof(rule) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX deposit_proposals_age ON deposit_proposals (created_at);
        """
    )
