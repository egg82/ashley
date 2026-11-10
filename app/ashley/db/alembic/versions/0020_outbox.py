"""The outbox: replies said to a thread outside the response to a message, each deleted when its channel takes it."""

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE outbox (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            thread text NOT NULL CHECK (thread ~ '\S'),
            conversation_id bigint NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
            medium text NOT NULL CHECK (medium IN ('spoken', 'text')),
            body text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE outbox")
