"""The session sense moves onto Watches (`ashley.watches`): each session she was watching (`herdr_watched`) becomes a
`claude_session` hand-off watch whose baseline is the status and seq last recorded, with the kind's defaults as they
were when this ran, and the table goes."""

from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"

_WHEN = ('[[{"kind": "one_of", "negate": false, "field": "status", "values": ["blocked", "done"]},'
         ' {"kind": "changed", "negate": false, "field": "seq"}],'
         ' [{"kind": "equals", "negate": false, "field": "status", "value": "idle"},'
         ' {"kind": "changed", "negate": false, "field": "seq"},'
         ' {"kind": "equals", "negate": true, "field": "status", "value": "done", "of": "before"}]]')
_UNTIL = '[[{"kind": "gone", "negate": false}]]'


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO watches (household_id, person_id, kind, target, label, bench_id, armed_by, track, when_clauses,
                             until_clauses, interval_s, expires_at, baseline)
        SELECT household_id, person_id, 'claude_session', session_id, left(coalesce(nullif(label, ''), session_id), 100),
               bench_id, 'handoff', ARRAY['status', 'seq'], '{_WHEN}'::jsonb, '{_UNTIL}'::jsonb, 15,
               now() + make_interval(hours => 72),
               jsonb_build_object(session_id, jsonb_build_object('status', status, 'seq', seq))
        FROM herdr_watched WHERE length(session_id) BETWEEN 1 AND 200""")
    op.execute("DROP TABLE herdr_watched")


def downgrade() -> None:
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
