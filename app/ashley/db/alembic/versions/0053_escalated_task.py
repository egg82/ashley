"""The spend ledger knows the escalated task."""

from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'escalated', 'memory_write', 'memory_judge', 'look_up',
                                'transcribe', 'speak', 'embed', 'voiceprint'));
        """
    )
