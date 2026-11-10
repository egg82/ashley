"""The memory tasks in the inference spend ledger: the write job's decision and the memory eval's judge."""

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'memory_write', 'memory_judge', 'transcribe', 'speak'));
        """
    )
