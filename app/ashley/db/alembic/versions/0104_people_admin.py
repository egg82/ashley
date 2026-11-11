"""Who is an admin of the deployment: who may change what every household shares (a model provider's key).

`people.admin` is the app's own record, used while `ADMIN_GROUP` is unset. A deployment that already has people keeps
today's behaviour: every person of its first household (id 1) becomes one, and an admin revokes the rest from the web.
`sessions.admin` is what the provider's group said at the sign-in that opened the session, used while `ADMIN_GROUP` is
set; a session opened before it is no admin's."""

from alembic import op

revision: str = "0104"
down_revision: str | None = "0103"


def upgrade() -> None:
    op.execute("ALTER TABLE people ADD COLUMN admin boolean NOT NULL DEFAULT false")
    op.execute("UPDATE people SET admin = true WHERE household_id = 1")
    op.execute("ALTER TABLE sessions ADD COLUMN admin boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN admin")
    op.execute("ALTER TABLE people DROP COLUMN admin")
