"""The workshop: benches, each a person's, its pieces as they stand, and its command log, which replayed from empty
reproduces the pieces. Every row names its household, and each reference carries it, so nothing crosses households."""

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE benches (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            owner_id bigint NOT NULL,
            title text NOT NULL CHECK (title ~ '\S'),
            next_seq integer NOT NULL DEFAULT 1 CHECK (next_seq >= 1),
            opened_at timestamptz NOT NULL DEFAULT now(),
            closed_at timestamptz,
            UNIQUE (id, household_id),
            FOREIGN KEY (owner_id, household_id) REFERENCES people (id, household_id)
        );

        CREATE INDEX benches_open_by_owner ON benches (owner_id, opened_at DESC, id DESC) WHERE closed_at IS NULL;

        CREATE TABLE bench_pieces (
            bench_id bigint NOT NULL,
            household_id bigint NOT NULL,
            piece_id integer NOT NULL,
            kind text NOT NULL,
            title text NOT NULL,
            body text NOT NULL,
            version integer NOT NULL CHECK (version >= 1),
            place_order integer NOT NULL CHECK (place_order >= 0),
            place_size text NOT NULL CHECK (place_size IN ('small', 'medium', 'large', 'full')),
            changed_by integer NOT NULL,
            PRIMARY KEY (bench_id, piece_id),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id)
        );

        CREATE TABLE bench_commands (
            bench_id bigint NOT NULL,
            household_id bigint NOT NULL,
            seq integer NOT NULL CHECK (seq >= 1),
            at timestamptz NOT NULL DEFAULT now(),
            person_id bigint,
            command jsonb NOT NULL,
            outcome text NOT NULL,
            effect jsonb,
            PRIMARY KEY (bench_id, seq),
            CHECK ((outcome = 'accepted') = (effect IS NOT NULL)),
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id)
        );
        """
    )
