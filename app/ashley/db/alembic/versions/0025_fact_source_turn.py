"""A fact records the turn it was learned from, in its source conversation. Null for facts from before."""

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE turns ADD CONSTRAINT turns_id_conversation_key UNIQUE (id, conversation_id);

        ALTER TABLE facts
            ADD COLUMN source_turn_id bigint,
            ADD CONSTRAINT facts_source_turn_fkey
                FOREIGN KEY (source_turn_id, source_conversation_id) REFERENCES turns (id, conversation_id);

        CREATE INDEX facts_by_source_turn ON facts (source_turn_id) WHERE source_turn_id IS NOT NULL;
        """
    )
