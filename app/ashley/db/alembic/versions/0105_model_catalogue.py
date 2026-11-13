"""The model catalogue's stored layers: the last good fetch of models.dev's list, one row replaced whole, and a person's
overrides, one row per field of one model, so a field nobody set follows upstream. An override is kept, with no
setter, when the person who set it is gone."""

from alembic import op

revision: str = "0105"
down_revision: str | None = "0104"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_catalogue_fetch (
            only_row boolean PRIMARY KEY DEFAULT true CHECK (only_row),
            catalogue jsonb NOT NULL,
            fetched_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE model_catalogue_overrides (
            provider text NOT NULL,
            model text NOT NULL,
            field text NOT NULL,
            value jsonb NOT NULL,
            person_id bigint REFERENCES people (id) ON DELETE SET NULL,
            set_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, model, field)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE model_catalogue_overrides")
    op.execute("DROP TABLE model_catalogue_fetch")
