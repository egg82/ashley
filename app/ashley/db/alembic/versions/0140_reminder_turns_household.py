"""A reminder's, errand check's or standing errand's turn is the household's (`channels.wake.reminder_turn`): one stored
before this as a person turn of the person it was for becomes the household's, with no speaker, and its text, which
was her instructions, becomes the line the page shows (`reminder_turn.shown`).

Such a turn is found by its fields: a person turn whose `source` is `wake:<id>`, which only a wake's turn carries
(the house wakes and watches were made the household's by 0044). Its wake row gives the kind and the brief. A settled
reminder's row is pruned after a week, so for a turn whose row is gone the kind is read from the fixed opening its
instructions began with. That opening was written by our code (`reminder_turn.said`), never by a person, and has not
changed since each kind was added, so matching it here is matching our own marker, not natural language; it only
picks the label's first word, and a turn matching none is labelled a reminder. Live code reads the author, never
this text. With its row gone the line has no brief. On a shared device the line names only whom it was for."""

from alembic import op

revision: str = "0140"
down_revision: str | None = "0139"


def upgrade() -> None:
    op.execute(
        """
        WITH found AS (
            SELECT t.id, t.visibility, w.brief, p.name,
                   CASE WHEN w.ends_at IS NOT NULL OR (w.id IS NULL AND starts_with(t.text,
                            '[An errand you are carrying out over time, not words anyone said:')) THEN 'Errand check'
                        WHEN w.method IS NOT NULL OR (w.id IS NULL AND starts_with(t.text,
                            '[A standing errand you carry out each time it comes round, not words anyone said:'))
                            THEN 'Standing errand'
                        ELSE 'Reminder' END AS kind
            FROM turns t
            LEFT JOIN wakes w ON w.kind = 'reminder' AND w.household_id = t.household_id AND t.source = 'wake:' || w.id
            LEFT JOIN people p ON p.id = t.speaker_id
            WHERE t.author = 'person' AND t.source LIKE 'wake:%'
        )
        UPDATE turns t
        SET author = 'household', speaker_id = NULL,
            text = CASE WHEN f.visibility = 'shared' THEN f.kind || coalesce(' for ' || f.name, '')
                        ELSE f.kind || coalesce(': ' || f.brief, '') END
        FROM found f
        WHERE t.id = f.id
        """
    )


def downgrade() -> None:
    """The converted turns stay the household's: the earlier schema and code read them as any household turn, and the
    instructions they held are not kept to restore."""
