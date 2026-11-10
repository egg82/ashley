"""A Claude Code bench job whose person's machine is not answering waits (`bench_jobs.state` `waiting`) instead of
failing, and ends `failed` at its deadline if it never answers."""

from alembic import op

revision: str = "0097"
down_revision: str | None = "0096"

_STATES = "'due', 'starting', 'running', 'blocked', 'done', 'failed', 'timed_out', 'cancelled'"


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE bench_jobs DROP CONSTRAINT bench_jobs_state_check,
            ADD CONSTRAINT bench_jobs_state_check CHECK (state IN ({_STATES}, 'waiting'))""")


def downgrade() -> None:
    op.execute("UPDATE bench_jobs SET state = 'due', claimed_at = NULL WHERE state = 'waiting'")
    op.execute(f"""
        ALTER TABLE bench_jobs DROP CONSTRAINT bench_jobs_state_check,
            ADD CONSTRAINT bench_jobs_state_check CHECK (state IN ({_STATES}))""")
