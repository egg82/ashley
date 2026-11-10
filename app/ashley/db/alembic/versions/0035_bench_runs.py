"""A code run may be a bench's: the Run command it was made by (`bench_id`, `bench_seq`) and the piece and version it
ran, beside or instead of the turn that asked. A person's press of Run has no turn; her `bench_run` has both."""

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE code_runs
            ALTER COLUMN conversation_id DROP NOT NULL,
            ALTER COLUMN turn_id DROP NOT NULL,
            ALTER COLUMN call_id DROP NOT NULL,
            ADD COLUMN bench_id bigint,
            ADD COLUMN bench_seq integer,
            ADD COLUMN piece_id integer,
            ADD COLUMN piece_version integer,
            ADD CHECK ((conversation_id IS NULL) = (turn_id IS NULL) AND (turn_id IS NULL) = (call_id IS NULL)),
            ADD CHECK ((bench_id IS NULL) = (bench_seq IS NULL) AND (bench_seq IS NULL) = (piece_id IS NULL)
                       AND (piece_id IS NULL) = (piece_version IS NULL)),
            ADD CHECK (turn_id IS NOT NULL OR bench_id IS NOT NULL),
            ADD FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id),
            ADD FOREIGN KEY (bench_id, bench_seq) REFERENCES bench_commands (bench_id, seq),
            ADD UNIQUE (bench_id, bench_seq);

        CREATE INDEX code_runs_piece ON code_runs (bench_id, piece_id, id DESC) WHERE bench_id IS NOT NULL;
        """
    )
