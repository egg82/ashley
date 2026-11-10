"""Sign-in is for any OIDC provider, so the `authentik` account system, and the refused sign-ins recorded under it,
are named `oidc`. One UPDATE each, so a second run finds nothing to do."""

from alembic import op

revision: str = "0098"
down_revision: str | None = "0097"


def upgrade() -> None:
    op.execute("UPDATE accounts SET system = 'oidc' WHERE system = 'authentik'")
    op.execute("UPDATE signin_unmapped SET system = 'oidc' WHERE system = 'authentik'")


def downgrade() -> None:
    op.execute("UPDATE accounts SET system = 'authentik' WHERE system = 'oidc'")
    op.execute("UPDATE signin_unmapped SET system = 'authentik' WHERE system = 'oidc'")
