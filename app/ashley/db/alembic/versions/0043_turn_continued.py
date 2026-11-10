"""A turn of hers that points the reader to a bench (`continued_on`: the bench id), where the rest of her reply was
said, and the person turn a bench's talk opens with, which carries a chat turn (`carried_from`: that turn's id),
stored once per chat turn."""

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE turns ADD COLUMN carried_from bigint REFERENCES turns (id);
        ALTER TABLE turns ADD COLUMN continued_on bigint;
        ALTER TABLE turns ADD CONSTRAINT turns_carried_person CHECK (author = 'person' OR carried_from IS NULL);
        ALTER TABLE turns ADD CONSTRAINT turns_continued_hers CHECK (author = 'ashley' OR continued_on IS NULL);
        CREATE UNIQUE INDEX turns_carried_from ON turns (carried_from) WHERE carried_from IS NOT NULL;
        """
    )
