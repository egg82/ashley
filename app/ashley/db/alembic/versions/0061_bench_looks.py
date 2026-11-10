"""Her looks at a bench, one row per tool call that took one, tied to the person turn that asked: the picture she was
given is an object in the object store and this row names it, so what she saw is shown with the turn."""

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bench_looks (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL REFERENCES turns (id) ON DELETE CASCADE,
            call_id text NOT NULL,
            bench_id bigint NOT NULL,
            piece_id bigint,
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            media_type text NOT NULL,
            size integer NOT NULL CHECK (size > 0),
            looked_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (turn_id, call_id),
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id) ON DELETE CASCADE
        );

        CREATE INDEX bench_looks_conversation ON bench_looks (conversation_id);
        """
    )
