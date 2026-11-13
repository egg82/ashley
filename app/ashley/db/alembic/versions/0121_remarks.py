"""The remarks nobody asked for that she was allowed to make (`ashley.channels.remarks.Remarks`): one row per message
she was allowed a remark on, claimed before her turn and settled after it with the fingerprint of the line that went
out, or none, so the cap per person per day and "never the same line" are counted from what she did."""

from alembic import op

revision: str = "0121"
down_revision: str | None = "0112"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE remarks (
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            source text NOT NULL,
            person_id bigint NOT NULL,
            claimed_at timestamptz NOT NULL,
            settled boolean NOT NULL DEFAULT false,
            line text CHECK (settled OR line IS NULL),
            PRIMARY KEY (household_id, source),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        );
        CREATE INDEX remarks_person ON remarks (household_id, person_id, claimed_at);
        CREATE INDEX remarks_claimed ON remarks (claimed_at);
        """)


def downgrade() -> None:
    op.execute("DROP TABLE remarks")
