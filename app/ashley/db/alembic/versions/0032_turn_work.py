"""A turn's work in flight, one row per person turn being answered: its claim and the turn loop's checkpoint, deleted
when her turn is stored."""

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE turn_work (
            said_id bigint PRIMARY KEY REFERENCES turns (id) ON DELETE CASCADE,
            conversation_id bigint NOT NULL,
            household_id bigint NOT NULL,
            holder text NOT NULL,
            claimed_until timestamptz NOT NULL,
            attempts integer NOT NULL DEFAULT 1 CHECK (attempts >= 1),
            checkpoint text NOT NULL,
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id) ON DELETE CASCADE
        );

        CREATE INDEX turn_work_claimed_until ON turn_work (claimed_until);
        """
    )
