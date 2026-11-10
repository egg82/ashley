"""A person's own connection to a code host, kinds `gitlab` and `github`: the connection row names its person
(`person_id`, set for exactly those kinds), so a household holds one of a kind per person, and the other kinds stay one
per household."""

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"


def upgrade() -> None:
    op.execute("ALTER TABLE connections DROP CONSTRAINT connections_kind_check")
    op.execute("ALTER TABLE connections ADD CONSTRAINT connections_kind_check "
               "CHECK (kind IN ('sure', 'home_assistant', 'gitlab', 'github'))")
    op.execute("ALTER TABLE connections ADD COLUMN person_id bigint REFERENCES people (id) ON DELETE CASCADE")
    op.execute("ALTER TABLE connections ADD CONSTRAINT connections_owner_check "
               "CHECK ((kind IN ('gitlab', 'github')) = (person_id IS NOT NULL))")
    op.execute("ALTER TABLE connections DROP CONSTRAINT connections_household_id_kind_key")
    op.execute("CREATE UNIQUE INDEX connections_owner_key ON connections (household_id, kind, COALESCE(person_id, 0))")
