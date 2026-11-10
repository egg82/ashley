"""A conversation records the thread it started on, so a thread's whole history can be read back after the thread has
moved to a newer conversation. Conversations from before are placed only where a thread still points at them."""

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations ADD COLUMN thread text;

        UPDATE conversations c SET thread = t.thread
        FROM conversation_threads t
        WHERE t.conversation_id = c.id AND t.household_id = c.household_id;

        CREATE INDEX conversations_thread_idx ON conversations (household_id, thread, last_activity_at DESC, id DESC)
            WHERE thread IS NOT NULL;
        """
    )
