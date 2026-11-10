"""A code run's language may be `build123d` as well as `python`: the constraint on `code_runs.language` names both.
Downgrade deletes the build123d runs, which the older constraint refuses."""

from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE code_runs DROP CONSTRAINT code_runs_language_check;
        ALTER TABLE code_runs ADD CONSTRAINT code_runs_language_check CHECK (language IN ('python', 'build123d'));
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM code_runs WHERE language <> 'python';
        ALTER TABLE code_runs DROP CONSTRAINT code_runs_language_check;
        ALTER TABLE code_runs ADD CONSTRAINT code_runs_language_check CHECK (language IN ('python'));
    """)
