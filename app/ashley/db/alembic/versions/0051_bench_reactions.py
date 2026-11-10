"""A bench's reactions: each time she reacted to a person's changes on it, up to the command `seq` she was handed
(`to_seq`). The newest row's `to_seq` is the last command she has seen, so the next reaction is handed only what the
person did after it; the rows in the window are what bounds how often she reacts. A bench that already had changes
starts with a record at its newest one, so she does not react to work from before."""

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bench_reactions (
            bench_id bigint NOT NULL,
            household_id bigint NOT NULL,
            to_seq integer NOT NULL CHECK (to_seq >= 1),
            at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (bench_id, to_seq),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id)
        );

        CREATE INDEX bench_reactions_recent ON bench_reactions (bench_id, at DESC);

        INSERT INTO bench_reactions (bench_id, household_id, to_seq, at)
            SELECT bench_id, household_id, max(seq), to_timestamp(0) FROM bench_commands
            WHERE person_id IS NOT NULL AND outcome = 'accepted' GROUP BY bench_id, household_id;
        """
    )
