"""Whether a site piece's address can be shown in a frame, measured once per address on a bench: `frameable` is null when
the address could not be measured, and a row exists so it is not asked again until the address is back on the bench."""

from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE bench_site_frames (
            bench_id bigint NOT NULL,
            household_id bigint NOT NULL,
            url text NOT NULL,
            frameable boolean,
            title text NOT NULL DEFAULT '',
            checked_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (bench_id, url),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id) ON DELETE CASCADE
        );
        """
    )
