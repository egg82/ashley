"""The model a household chose for each chat-facing task, by provider and model name: the route it stands for is
resolved from the deployment's routes when read, so nothing here is a timeout or a parameter. Gone with its household;
kept, with no setter, when the person who set it is gone."""

from alembic import op

revision: str = "0102"
down_revision: str | None = "0101"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE household_routes (
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            task text NOT NULL,
            provider text NOT NULL,
            model text NOT NULL,
            person_id bigint REFERENCES people (id) ON DELETE SET NULL,
            set_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (household_id, task)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE household_routes")
