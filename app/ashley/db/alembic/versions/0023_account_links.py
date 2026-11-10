"""A person links their own Discord account from the web app: the links in flight, each bound to the person who started
it, and the account's handle as it was when linked, shown to its person only. A link in flight is its own table, never
a sign-in's, so a state from one flow can never complete the other. States are stored only as their SHA-256."""

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE accounts ADD COLUMN handle text NOT NULL DEFAULT '';

        CREATE TABLE link_pending (
            state_sha256 bytea PRIMARY KEY CHECK (length(state_sha256) = 32),
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            verifier text NOT NULL CHECK (verifier ~ '\S'),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        );
        """
    )
