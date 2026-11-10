"""The spend ledger names the conversation a call served. A bare id with no foreign key and no household: the ledger
holds nothing said or known about anyone, and an id that outlives its conversation is fine."""

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"


def upgrade() -> None:
    op.execute("ALTER TABLE inference_calls ADD COLUMN conversation_id bigint;")
