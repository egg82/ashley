"""A person turn may carry its channel's id for the message (`source`), stored once per household, so a message handed
to the turn loop twice is one turn; and a Discord claim records when the turn loop took the message in hand
(`settled_at`), so a session catching up hands in again only the claims a dead session left. Existing claims are
settled: they were answered, or are past saving."""

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE turns ADD COLUMN source text;
        ALTER TABLE turns ADD CONSTRAINT turns_source_person CHECK (author = 'person' OR source IS NULL);
        CREATE UNIQUE INDEX turns_source ON turns (household_id, source) WHERE source IS NOT NULL;

        ALTER TABLE discord_seen ADD COLUMN settled_at timestamptz;
        UPDATE discord_seen SET settled_at = claimed_at;
        """
    )
