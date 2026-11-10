"""A household's own location, set by its people on the household page: the house's latitude and longitude in degrees,
both set or both null. A household starts with none."""

from alembic import op

revision: str = "0101"
down_revision: str | None = "0099"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE households
            ADD COLUMN latitude double precision,
            ADD COLUMN longitude double precision,
            ADD CONSTRAINT households_location CHECK (
                (latitude IS NULL AND longitude IS NULL)
                OR (latitude IS NOT NULL AND longitude IS NOT NULL
                    AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180))""")


def downgrade() -> None:
    op.execute("ALTER TABLE households DROP CONSTRAINT households_location, DROP COLUMN latitude, DROP COLUMN longitude")
