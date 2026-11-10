"""A person's pending proposals of a person-scoped topic (`ashley.senses.proposal_payloads.OUTSIDE`) are looked up by
person and topic across conversations, so `proposals` gets an index on `(made_by, topic, id)`."""

from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"


def upgrade() -> None:
    op.execute("CREATE INDEX proposals_person_topic ON proposals (made_by, topic, id)")


def downgrade() -> None:
    op.execute("DROP INDEX proposals_person_topic")
