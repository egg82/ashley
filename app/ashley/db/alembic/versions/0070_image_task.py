"""The spend ledger knows the image task: her generated pictures."""

from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'escalated', 'wrap_up', 'memory_write', 'memory_judge',
                                'look_up', 'bench_tidy', 'transcribe', 'speak', 'embed', 'voiceprint', 'image'));
        """
    )
