"""The memory write job's bookkeeping, one row per conversation it has tried: the newest turn already written into
memory, and the run of failed writes since. Its own table rather than columns on `conversations`, because it is
Memory's state, not the conversation's, and only Memory writes it."""

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE memory_writes (
            conversation_id bigint PRIMARY KEY,
            household_id bigint NOT NULL,
            written_turn_id bigint,
            failures integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
            failed_turn_id bigint,
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id)
        );
        """
    )
