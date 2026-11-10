"""What an Install, or the Undo of one, did to the house: one row per such bench command, written before its first
write to Home Assistant (with what HA held before) and again when it ended."""

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bench_installs (
            bench_id bigint NOT NULL,
            household_id bigint NOT NULL,
            seq integer NOT NULL,
            piece_id integer NOT NULL,
            action text NOT NULL CHECK (action IN ('install', 'uninstall')),
            automation_id text NOT NULL,
            enabled boolean,
            turn_off text,
            before jsonb,
            touched boolean NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            ending text CHECK (ending IN ('done', 'refused', 'failed')),
            note text,
            finished_at timestamptz,
            PRIMARY KEY (bench_id, seq),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id),
            FOREIGN KEY (bench_id, seq) REFERENCES bench_commands (bench_id, seq),
            CHECK ((ending IS NULL) = (finished_at IS NULL))
        );

        CREATE INDEX bench_installs_piece ON bench_installs (bench_id, piece_id, seq DESC);
        """
    )
