"""Contract 15's route: `POST /api/benches/{b}/jobs/{j}/cancel`, the job piece's Cancel button, through the real app over a
real database. Jobs are inserted as rows (the columns of I12) because the app runs on its own event loop."""

import psycopg
from bjb_support import state_of
from respond_support import ALANA, SAM, wired as wired
from test_workshop_routes import As, opened
from test_workshop_routes import signed_in as signed_in
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


def job_on(url: str, bench: int, person: int, group: int = 1) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        conversation = conn.execute("INSERT INTO conversations (household_id, kind) VALUES (%s, 'brainstorm') RETURNING id",
                                    (ALANA.household_id,)).fetchone()
        assert conversation is not None
        turn = conn.execute("INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                            "VALUES (%s, %s, 'person', %s, 'go', 'shared') RETURNING id",
                            (conversation[0], ALANA.household_id, person)).fetchone()
        assert turn is not None
        made = conn.execute(
            "INSERT INTO bench_jobs (household_id, person_id, bench_id, conversation_id, turn_id, worker, title, brief, "
            "pieces, piece_id, state, group_id) VALUES (%s, %s, %s, %s, %s, 'agent', 'Gate', 'Build it.', '[]'::jsonb, 1, "
            "'due', %s) RETURNING id", (ALANA.household_id, person, bench, conversation[0], turn[0], group)).fetchone()
        assert made is not None
        return int(made[0])


def test_c15_the_owner_cancels_a_job_through_the_route_once(signed_in: As, db_url: str) -> None:
    client = signed_in(ALANA)
    bench = opened(client)
    job = job_on(db_url, bench.id, ALANA.id)
    first = client.post(f"/api/benches/{bench.id}/jobs/{job}/cancel")
    assert first.status_code in (200, 202, 204), first.text
    assert state_of(db_url, job) == "cancelled"
    again = client.post(f"/api/benches/{bench.id}/jobs/{job}/cancel")
    assert again.status_code == 200 and again.json()["state"] == "cancelled" and state_of(db_url, job) == "cancelled"  # AMBIGUITY: a repeat is idempotent


def test_c15_another_person_cannot_cancel_it_and_it_stays(signed_in: As, db_url: str) -> None:
    mine = signed_in(ALANA)
    bench = opened(mine)
    job = job_on(db_url, bench.id, ALANA.id)
    theirs = signed_in(SAM)
    got = theirs.post(f"/api/benches/{bench.id}/jobs/{job}/cancel")
    assert got.status_code == 404 and state_of(db_url, job) == "due"


def test_c15_a_job_named_under_another_bench_is_not_found(signed_in: As, db_url: str) -> None:
    client = signed_in(ALANA)
    bench, other = opened(client), opened(client, "other")
    job = job_on(db_url, bench.id, ALANA.id)
    got = client.post(f"/api/benches/{other.id}/jobs/{job}/cancel")
    assert got.status_code == 404 and state_of(db_url, job) == "due"


def test_c15_an_unknown_job_is_not_found(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client)
    assert client.post(f"/api/benches/{bench.id}/jobs/987654/cancel").status_code == 404
