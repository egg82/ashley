"""What a person lets her just do (`ashley.trust`): one revision row per person counting their writes, one row per kind
whose value differs from what it is unset, and a log row per changed kind, pruned by the writer. Every row names the
household with the person, so a read keyed on both never reaches another household's."""

from alembic import op

revision: str = "0142"
down_revision: str | None = "0141"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE trust_revisions (
            household_id bigint NOT NULL,
            person_id bigint PRIMARY KEY,
            version integer NOT NULL CHECK (version >= 0),
            updated_at timestamptz,
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        );

        CREATE TABLE trust_settings (
            household_id bigint NOT NULL,
            person_id bigint NOT NULL REFERENCES trust_revisions (person_id) ON DELETE CASCADE,
            kind text NOT NULL,
            value text NOT NULL CHECK (value IN ('act', 'offer')),
            PRIMARY KEY (person_id, kind)
        );

        CREATE TABLE trust_settings_log (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            kind text NOT NULL,
            before text CHECK (before IN ('act', 'offer')),
            after text CHECK (after IN ('act', 'offer')),
            changed_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE trust_settings_log; DROP TABLE trust_settings; DROP TABLE trust_revisions")
