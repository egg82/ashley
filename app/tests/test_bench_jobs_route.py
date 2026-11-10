"""`POST /api/benches/{b}/jobs/{j}/cancel`: the person's own job on that bench ends `cancelled`; a job of another
person, of another bench or none is 404 and is not cancelled; an unreachable store is 503."""

from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.errands.bench_jobs import BenchJobs, Job, JobsUnavailable, NullBenchJobs
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import ALANA, SAM, wired as wired
from test_workshop_routes import As, opened
from test_workshop_routes import signed_in as signed_in

NOW = datetime(2026, 11, 8, tzinfo=UTC)


class Held(NullBenchJobs):
    """The jobs by id; `cancel` is recorded and ends the job."""

    def __init__(self, rows: dict[int, Job]) -> None:
        self.rows, self.down = rows, False
        self.cancelled: list[int] = []

    async def get(self, household_id: int, person_id: int, job_id: int) -> Job | None:
        if self.down:
            raise JobsUnavailable("down")
        row = self.rows.get(job_id)
        return row if row is not None and (row.household_id, row.person_id) == (household_id, person_id) else None

    async def cancel(self, household_id: int, person_id: int, job_id: int) -> bool:
        self.cancelled.append(job_id)
        self.rows[job_id] = replace(self.rows[job_id], state="cancelled", finished_at=NOW)
        return True


def job(bench: int, person: int, household: int = 1) -> Job:
    return Job(5, household, person, bench, 1, 1, 7, "agent", "t", "b", (), (), 1, "running", 1, None, 0, None, NOW, None,
               None, None, None, (), 0)


@pytest.fixture
def jobs(signed_in: As) -> Generator[Held]:
    held = Held({})
    services.register(BenchJobs, held)
    yield held
    services.unregister(BenchJobs)


def test_the_owner_cancels_a_job_on_that_bench(signed_in: As, jobs: Held) -> None:
    client = signed_in(ALANA)
    bench = opened(client)
    jobs.rows[5] = job(bench.id, ALANA.id, ALANA.household_id)
    got = client.post(f"/api/benches/{bench.id}/jobs/5/cancel")
    assert got.status_code == 200 and got.json() == {"job": 5, "state": "cancelled"} and jobs.cancelled == [5]


def test_another_persons_job_another_bench_and_no_job_are_404_and_nothing_is_cancelled(signed_in: As, jobs: Held) -> None:
    client = signed_in(ALANA)
    bench, other = opened(client), opened(client, "other")
    jobs.rows[5] = job(bench.id, SAM.id, ALANA.household_id)
    jobs.rows[6] = job(other.id, ALANA.id, ALANA.household_id)
    assert client.post(f"/api/benches/{bench.id}/jobs/5/cancel").status_code == 404
    assert client.post(f"/api/benches/{bench.id}/jobs/6/cancel").status_code == 404
    assert client.post(f"/api/benches/{bench.id}/jobs/99/cancel").status_code == 404
    assert jobs.cancelled == []


def test_an_unreachable_store_is_503(signed_in: As, jobs: Held) -> None:
    client = signed_in(ALANA)
    bench = opened(client)
    jobs.down = True
    assert client.post(f"/api/benches/{bench.id}/jobs/5/cancel").status_code == 503
