"""A turn records who could hear it, so a reply carries it only where the same people would: `shared` when the household
could, `private` to its `owner_id` when only they could. A turn that names neither is private to no one, so no reply
carries it; from before, that is every turn except a web conversation's with one participant, which only they could
read, so it is theirs. Their words are searchable, for the turns relevant to a message."""

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE turns
            ADD COLUMN visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('shared', 'private')),
            ADD COLUMN owner_id bigint,
            ADD COLUMN search tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
            ADD FOREIGN KEY (owner_id, household_id) REFERENCES people (id, household_id);

        CREATE INDEX turns_search ON turns USING gin (search);

        UPDATE turns t SET owner_id = only_one.person_id
        FROM (SELECT p.conversation_id, min(p.person_id) AS person_id
              FROM conversation_participants p JOIN conversations c ON c.id = p.conversation_id
              WHERE c.channel = 'web'
              GROUP BY p.conversation_id HAVING count(*) = 1) only_one
        WHERE t.conversation_id = only_one.conversation_id;
        """
    )
