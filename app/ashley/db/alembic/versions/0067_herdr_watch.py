"""The Claude Code sessions she watches (`herdr_watched`: what the poller last saw of each, and the bench that started
it) and the screens a person has open (`live_screens`: a row per open stream, refreshed while it is, so a pod on either
site can tell whether anyone is looking)."""

from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE herdr_watched (
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            person_id bigint NOT NULL REFERENCES people (id) ON DELETE CASCADE,
            session_id text NOT NULL,
            label text NOT NULL,
            bench_id bigint,
            status text NOT NULL,
            seq bigint NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            seen_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (person_id, session_id)
        )""")
    op.execute("""
        CREATE TABLE live_screens (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            person_id bigint NOT NULL REFERENCES people (id) ON DELETE CASCADE,
            seen_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX live_screens_person ON live_screens (person_id, seen_at)")


def downgrade() -> None:
    op.execute("DROP TABLE live_screens")
    op.execute("DROP TABLE herdr_watched")
