"""Links between a bench's pieces (`ashley.workshop.links`): one row for each link the bench holds, made by the command
`seq`. A row stays while an end piece is removed or shelved, since an undo or a restore brings the piece back with
its links; a read shows only rows whose two ends are both on the layout."""

from alembic import op

revision: str = "0136"
down_revision: str | None = "0135"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE bench_links (
            bench_id bigint NOT NULL,
            household_id bigint NOT NULL,
            from_piece integer NOT NULL,
            kind text NOT NULL,
            to_piece integer NOT NULL CHECK (to_piece <> from_piece),
            seq integer NOT NULL CHECK (seq >= 1),
            PRIMARY KEY (bench_id, from_piece, kind, to_piece),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id)
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE bench_links")
