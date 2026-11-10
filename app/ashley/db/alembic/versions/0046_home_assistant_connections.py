"""A household's Home Assistant is one of its connections, kind `home_assistant`: its base URL and a long-lived access
token, sealed as Sure's key is."""

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"


def upgrade() -> None:
    op.execute("ALTER TABLE connections DROP CONSTRAINT connections_kind_check")
    op.execute("ALTER TABLE connections ADD CONSTRAINT connections_kind_check "
               "CHECK (kind IN ('sure', 'home_assistant'))")
