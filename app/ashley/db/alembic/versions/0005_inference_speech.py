"""Speech calls in the inference spend ledger: the two speech tasks, and what they are billed by."""

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'transcribe', 'speak')),
            ADD COLUMN audio_ms integer CHECK (audio_ms >= 0),
            ADD COLUMN characters integer CHECK (characters >= 0);

        UPDATE inference_calls SET audio_ms = 0, characters = 0 WHERE input_tokens IS NOT NULL;
        """
    )
