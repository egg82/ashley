"""A person's catalogue providers: one row per field (name, api) of one provider, so a provider models.dev does not list
can be defined, and a field nobody set follows upstream, as `model_catalogue_overrides` does for a model. Kept, with no
setter, when the person who set it is gone."""

from alembic import op

revision: str = "0123"
down_revision: str | None = "0122"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_catalogue_provider_overrides (
            provider text NOT NULL,
            field text NOT NULL,
            value jsonb NOT NULL,
            person_id bigint REFERENCES people (id) ON DELETE SET NULL,
            set_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, field)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE model_catalogue_provider_overrides")
