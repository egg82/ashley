"""The spend ledger knows the eval_judge task."""

from alembic import op

revision: str = "0095"
down_revision: str | None = "0094"

_TASKS = ("'command', 'chat', 'brainstorm', 'escalated', 'wrap_up', 'memory_write', 'memory_judge', 'look_up', "
          "'bench_tidy', 'errand', 'action_judge', 'bench_job'")
_SPEND = "'transcribe', 'speak', 'embed', 'voiceprint', 'image'"


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check CHECK (task IN ({_TASKS}, 'eval_judge', {_SPEND}))""")


def downgrade() -> None:
    op.execute("DELETE FROM inference_calls WHERE task = 'eval_judge'")
    op.execute(f"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check CHECK (task IN ({_TASKS}, {_SPEND}))""")
