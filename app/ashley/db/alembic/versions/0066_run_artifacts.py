"""A bench run's binary outputs: `code_runs.artifacts` lists, for each kept file, its name in the working directory and the
sha256, size and media type of the bytes in the object store."""

from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"


def upgrade() -> None:
    op.execute("ALTER TABLE code_runs ADD COLUMN artifacts jsonb NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    op.execute("ALTER TABLE code_runs DROP COLUMN artifacts")
