"""A change to the house that needs a person's OK is proposed before it is carried out: `house_proposals` holds the change
she proposed and the turn it was proposed in, and it is taken only from a later turn of the same conversation."""

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE house_proposals (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            made_by bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL,
            change jsonb NOT NULL CHECK (jsonb_typeof(change) = 'object'),
            summary text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX house_proposals_age ON house_proposals (created_at);
        """
    )
