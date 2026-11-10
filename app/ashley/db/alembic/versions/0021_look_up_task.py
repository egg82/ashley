"""The spend ledger knows the look-up task."""

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'memory_write', 'memory_judge', 'look_up', 'transcribe',
                                'speak', 'embed', 'voiceprint'));
        """
    )
