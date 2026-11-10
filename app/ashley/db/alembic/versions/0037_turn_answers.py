"""Her turn records the person turn it answers. Existing turns of hers take the person turn before them, where that is
unambiguous: the turns of hers between two person turns are held lines and at most one answer, last."""

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE turns ADD COLUMN answers bigint;
        ALTER TABLE turns ADD CONSTRAINT turns_answers_fkey
            FOREIGN KEY (answers, conversation_id) REFERENCES turns (id, conversation_id);
        ALTER TABLE turns ADD CONSTRAINT turns_answers_hers CHECK (author = 'ashley' OR answers IS NULL);

        WITH hers AS (
            SELECT id, author, follows, max(id) FILTER (WHERE author = 'person') OVER (
                PARTITION BY conversation_id ORDER BY id) AS person_id
            FROM turns
        ), clear AS (
            SELECT person_id FROM hers WHERE person_id IS NOT NULL AND author = 'ashley'
            GROUP BY person_id
            HAVING count(*) FILTER (WHERE NOT follows) <= 1
               AND coalesce(max(id) FILTER (WHERE NOT follows), max(id)) = max(id)
        )
        UPDATE turns t SET answers = h.person_id
        FROM hers h JOIN clear c ON c.person_id = h.person_id
        WHERE t.id = h.id AND h.author = 'ashley';
        """
    )
