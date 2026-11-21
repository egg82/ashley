"""Shadow runs of automation pieces: `bench_installs.shadow` marks an install of one and the uninstall of one;
`automation_shadows` is each run (its end time kept here, so any pod ends it) and `automation_shadow_firings` what was
recorded in it: the piece's would-have-fired events and the real automation's did-fire events."""

from alembic import op

revision: str = "0132"
down_revision: str | None = "0131"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bench_installs ADD COLUMN shadow boolean NOT NULL DEFAULT false;

        CREATE TABLE automation_shadows (
            bench_id bigint NOT NULL,
            install_seq integer NOT NULL,
            household_id bigint NOT NULL,
            piece_id integer NOT NULL,
            version integer NOT NULL,
            person_id bigint NOT NULL,
            mirrors text,
            started_at timestamptz NOT NULL,
            ends_at timestamptz NOT NULL,
            ended_at timestamptz,
            PRIMARY KEY (bench_id, install_seq),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id),
            CHECK (ends_at > started_at)
        );

        CREATE INDEX automation_shadows_live ON automation_shadows (household_id) WHERE ended_at IS NULL;

        CREATE TABLE automation_shadow_firings (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL,
            bench_id bigint NOT NULL,
            install_seq integer NOT NULL,
            kind text NOT NULL CHECK (kind IN ('would', 'did')),
            fired_at timestamptz NOT NULL,
            context text NOT NULL,
            FOREIGN KEY (bench_id, install_seq) REFERENCES automation_shadows (bench_id, install_seq) ON DELETE CASCADE,
            UNIQUE (bench_id, install_seq, kind, context)
        );

        CREATE INDEX automation_shadow_firings_at ON automation_shadow_firings (fired_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE automation_shadow_firings;
        DROP TABLE automation_shadows;
        DELETE FROM bench_installs WHERE shadow;
        ALTER TABLE bench_installs DROP COLUMN shadow;
        """
    )
