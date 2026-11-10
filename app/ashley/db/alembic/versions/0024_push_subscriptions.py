"""Web push: the browsers each person asked to be pushed to. An endpoint belongs to one person; its keys encrypt what is
sent, so the push service never reads it."""

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE push_subscriptions (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            endpoint text NOT NULL UNIQUE CHECK (endpoint ~ '^https://'),
            p256dh text NOT NULL CHECK (p256dh ~ '\S'),
            auth text NOT NULL CHECK (auth ~ '\S'),
            created_at timestamptz NOT NULL DEFAULT now(),
            last_success_at timestamptz,
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE
        );
        CREATE INDEX push_subscriptions_person ON push_subscriptions (person_id);
        """
    )
