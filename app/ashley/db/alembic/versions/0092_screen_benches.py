"""A device's screen is a bench of the device's (`benches.device_id`, owner null), laid out and logged as a person's bench
is. At most one per device. A device's touch controls move into the screen's `controls` piece when its bench is created;
`device_controls` keeps a device's rows until then."""

from alembic import op

revision: str = "0092"
down_revision: str | None = "0091"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE benches ALTER COLUMN owner_id DROP NOT NULL;
        ALTER TABLE benches ADD COLUMN device_id bigint;
        ALTER TABLE benches ADD CONSTRAINT benches_device_id_household_id_fkey
            FOREIGN KEY (device_id, household_id) REFERENCES devices (id, household_id);
        ALTER TABLE benches ADD CONSTRAINT benches_owner_or_device CHECK ((owner_id IS NULL) <> (device_id IS NULL));
        CREATE UNIQUE INDEX benches_screen ON benches (device_id) WHERE device_id IS NOT NULL;
        """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM bench_commands WHERE bench_id IN (SELECT id FROM benches WHERE device_id IS NOT NULL);
        DELETE FROM bench_pieces WHERE bench_id IN (SELECT id FROM benches WHERE device_id IS NOT NULL);
        DELETE FROM benches WHERE device_id IS NOT NULL;
        DROP INDEX benches_screen;
        ALTER TABLE benches DROP CONSTRAINT benches_owner_or_device;
        ALTER TABLE benches DROP COLUMN device_id;
        ALTER TABLE benches ALTER COLUMN owner_id SET NOT NULL;
        """)
