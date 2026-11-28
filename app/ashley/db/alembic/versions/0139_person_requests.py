"""Per-person request counts for the rate limit on what a person's screen makes her house do (`Sessions.allow`): one row
per person and fixed window, so every pod on either site counts in the same place. A row older than the window is deleted
by the person's next request."""

from alembic import op

revision: str = "0139"
down_revision: str | None = "0138"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE person_requests (
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            window_start timestamptz NOT NULL,
            requests integer NOT NULL CHECK (requests > 0),
            PRIMARY KEY (person_id, window_start),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        );
        """
    )
