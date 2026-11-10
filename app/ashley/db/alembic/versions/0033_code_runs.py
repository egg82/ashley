"""Her code runs, one row per run, tied to the person turn that asked for it: the job (language, script, input,
files) written before it runs, and what came out written after, so a run is never repeated and outlives its pod."""

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE code_runs (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL REFERENCES turns (id) ON DELETE CASCADE,
            call_id text NOT NULL,
            language text NOT NULL CHECK (language IN ('python')),
            script text NOT NULL,
            stdin text NOT NULL,
            files jsonb NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            outcome text CHECK (outcome IN ('ran', 'timed_out', 'out_of_memory', 'failed', 'unknown')),
            exit_code integer,
            stdout text,
            stderr text,
            cut boolean,
            out_files jsonb,
            skipped jsonb,
            CHECK ((finished_at IS NULL) = (outcome IS NULL)),
            FOREIGN KEY (conversation_id, household_id) REFERENCES conversations (id, household_id) ON DELETE CASCADE
        );

        CREATE INDEX code_runs_turn ON code_runs (turn_id);
        """
    )
