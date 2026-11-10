"""Bench jobs: work she hands to a worker from a bench, run later and told once its group settles
(`ashley.errands.bench_jobs`). The spend ledger knows the bench_job task."""

from alembic import op

revision: str = "0094"
down_revision: str | None = "0093"

_TASKS = ("'command', 'chat', 'brainstorm', 'escalated', 'wrap_up', 'memory_write', 'memory_judge', 'look_up', "
          "'bench_tidy', 'errand', 'action_judge'")
_SPEND = "'transcribe', 'speak', 'embed', 'voiceprint', 'image'"


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check CHECK (task IN ({_TASKS}, 'bench_job', {_SPEND}))""")
    op.execute("CREATE SEQUENCE bench_job_groups")
    op.execute("""
        CREATE TABLE bench_jobs (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            bench_id bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL,
            group_id bigint NOT NULL,
            worker text NOT NULL CHECK (worker IN ('agent', 'claude_code')),
            title text NOT NULL CHECK (title ~ '\\S'),
            brief text NOT NULL CHECK (brief ~ '\\S'),
            pieces jsonb NOT NULL DEFAULT '[]',
            made integer[] NOT NULL DEFAULT '{}',
            piece_id integer NOT NULL,
            state text NOT NULL DEFAULT 'due' CHECK (state IN ('due', 'starting', 'running', 'blocked', 'done',
                'failed', 'timed_out', 'cancelled')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            claimed_at timestamptz,
            session_id text,
            session_seq integer,
            prompted_at timestamptz,
            deadline_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            closed_at timestamptz,
            reason text,
            summary text,
            outputs integer[] NOT NULL DEFAULT '{}',
            refused integer NOT NULL DEFAULT 0 CHECK (refused >= 0),
            CHECK ((state IN ('done', 'failed', 'timed_out', 'cancelled')) = (finished_at IS NOT NULL)),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE,
            FOREIGN KEY (bench_id, household_id) REFERENCES benches (id, household_id) ON DELETE CASCADE,
            FOREIGN KEY (turn_id, conversation_id) REFERENCES turns (id, conversation_id) ON DELETE CASCADE
        )""")
    op.execute("CREATE INDEX bench_jobs_open ON bench_jobs (state, created_at) "
               "WHERE state NOT IN ('done', 'failed', 'timed_out', 'cancelled')")
    op.execute("CREATE INDEX bench_jobs_group ON bench_jobs (group_id)")


def downgrade() -> None:
    op.execute("DROP TABLE bench_jobs")
    op.execute("DROP SEQUENCE bench_job_groups")
    op.execute(f"""
        DELETE FROM inference_calls WHERE task = 'bench_job';
        ALTER TABLE inference_calls
            DROP CONSTRAINT inference_calls_task_check,
            ADD CONSTRAINT inference_calls_task_check CHECK (task IN ({_TASKS}, {_SPEND}))""")
