"""The tidy pass over a bench's text pieces: `bench_tidy` holds, per bench, the piece versions the last finished pass saw
and the time a running pass took the bench; `bench_findings` holds what a pass pointed at, kept until dismissed, fixed
or old. The spend ledger knows the bench_tidy task."""

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check
                CHECK (task IN ('command', 'chat', 'brainstorm', 'escalated', 'wrap_up', 'memory_write', 'memory_judge',
                                'look_up', 'bench_tidy', 'transcribe', 'speak', 'embed', 'voiceprint'));

        CREATE TABLE bench_tidy (
            bench_id bigint PRIMARY KEY,
            household_id bigint NOT NULL,
            versions jsonb NOT NULL DEFAULT '{}',
            running_at timestamptz,
            checked_at timestamptz,
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id) ON DELETE CASCADE
        );

        CREATE TABLE bench_findings (
            id bigserial PRIMARY KEY,
            bench_id bigint NOT NULL,
            household_id bigint NOT NULL,
            piece_id integer NOT NULL,
            kind text NOT NULL CHECK (kind IN ('superseded', 'contradicts', 'debris', 'duplicate')),
            quote text NOT NULL CHECK (quote <> ''),
            by_piece_id integer,
            why text NOT NULL,
            dismissed boolean NOT NULL DEFAULT false,
            found_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (bench_id, piece_id, quote),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id) ON DELETE CASCADE
        );
        """
    )
