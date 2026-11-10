"""A turn may be the household's (`author` `household`): the household speaking as itself (a wake), with no speaker, so it is never a
person's words. A wake turn stored before this as a person turn of the person it is about (its `source` `wake:<id>`)
becomes the household's."""

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE turns DROP CONSTRAINT turns_author_check;
        ALTER TABLE turns ADD CONSTRAINT turns_author_check CHECK (author IN ('person', 'ashley', 'household'));
        ALTER TABLE turns DROP CONSTRAINT turns_source_person;
        ALTER TABLE turns ADD CONSTRAINT turns_source_hers CHECK (author <> 'ashley' OR source IS NULL);
        UPDATE turns SET author = 'household', speaker_id = NULL WHERE author = 'person' AND source LIKE 'wake:%';
        """
    )
