"""The inference spend ledger: one row per model call."""

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE inference_calls (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            at timestamptz NOT NULL DEFAULT now(),
            task text NOT NULL CHECK (task IN ('command', 'chat', 'brainstorm')),
            provider text NOT NULL,
            model text NOT NULL,
            outcome text NOT NULL CHECK (outcome IN ('ok', 'refused', 'unavailable', 'invalid_output', 'error')),
            input_tokens integer,
            output_tokens integer,
            cache_read_tokens integer,
            cache_write_tokens integer,
            cost_usd numeric CHECK (cost_usd >= 0),
            duration_ms integer NOT NULL CHECK (duration_ms >= 0),
            CHECK ((input_tokens IS NULL) = (output_tokens IS NULL)
               AND (input_tokens IS NULL) = (cache_read_tokens IS NULL)
               AND (input_tokens IS NULL) = (cache_write_tokens IS NULL)),
            CHECK (input_tokens >= 0 AND output_tokens >= 0 AND cache_read_tokens >= 0 AND cache_write_tokens >= 0)
        );

        CREATE INDEX inference_calls_by_time ON inference_calls (at);
        """
    )
