"""Facts carry an embedding, made by the model named beside it, and the spend ledger knows the embed task. The vector
column is nullable: a fact is written whether or not the embedder answered, and the write job fills the gaps."""

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE EXTENSION IF NOT EXISTS vector;

        ALTER TABLE facts
            ADD COLUMN embedding vector(768),
            ADD COLUMN embedding_model text,
            ADD CONSTRAINT facts_embedding_has_model CHECK ((embedding IS NULL) = (embedding_model IS NULL));

        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'memory_write', 'memory_judge', 'transcribe', 'speak',
                                'embed'));
        """
    )
