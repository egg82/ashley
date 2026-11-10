"""The spend ledger knows the voiceprint task."""

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'memory_write', 'memory_judge', 'transcribe', 'speak',
                                'embed', 'voiceprint'));
        """
    )
