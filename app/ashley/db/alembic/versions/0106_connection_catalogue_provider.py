"""Which model catalogue provider a model-provider connection's calls are priced as: the one a person picked when they
added an OpenAI-compatible provider, null for a custom address and for every other kind of connection."""

from alembic import op

revision: str = "0106"
down_revision: str | None = "0105"


def upgrade() -> None:
    op.execute("ALTER TABLE connections ADD COLUMN catalogue_provider text")


def downgrade() -> None:
    op.execute("ALTER TABLE connections DROP COLUMN catalogue_provider")
