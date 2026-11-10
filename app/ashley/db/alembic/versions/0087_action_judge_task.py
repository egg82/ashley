"""The spend ledger knows the action_judge task."""

from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'escalated', 'wrap_up', 'memory_write', 'memory_judge',
                                'look_up', 'bench_tidy', 'errand', 'action_judge', 'transcribe', 'speak', 'embed',
                                'voiceprint', 'image'));
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        DELETE FROM inference_calls WHERE task = 'action_judge';
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'escalated', 'wrap_up', 'memory_write', 'memory_judge',
                                'look_up', 'bench_tidy', 'errand', 'transcribe', 'speak', 'embed', 'voiceprint', 'image'));
        """
    )
