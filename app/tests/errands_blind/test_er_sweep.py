"""sweep: a long-running errand is interrupted, an old due one expired; both counted, nothing else touched."""

from errands_blind_support import World, age_claimed, age_created, expired_of, interrupted_of, row, scenario


def test_sweep_interrupts_a_running_errand_claimed_too_long_ago(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, _ = await w.owed_claimed()
        age_claimed(w.url, eid, 500)
        counts = await w.errands.sweep(300, 100_000)
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "interrupted"
        assert r["finished_at"] is not None
        assert (interrupted_of(counts), expired_of(counts)) == (1, 0)

    scenario(db_url, body)


def test_sweep_leaves_a_recently_claimed_errand_running(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, _ = await w.owed_claimed()
        age_claimed(w.url, eid, 100)
        counts = await w.errands.sweep(300, 100_000)
        assert row(w.url, eid)["state"] == "running"
        assert (interrupted_of(counts), expired_of(counts)) == (0, 0)

    scenario(db_url, body)


def test_sweep_judges_a_running_errand_by_its_claim_not_its_age(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, _ = await w.owed_claimed()
        age_created(w.url, eid, 50_000)
        counts = await w.errands.sweep(300, 600)
        assert row(w.url, eid)["state"] == "running"
        assert (interrupted_of(counts), expired_of(counts)) == (0, 0)

    scenario(db_url, body)


def test_sweep_expires_a_due_errand_older_than_max_age(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        age_created(w.url, eid, 700)
        counts = await w.errands.sweep(300, 600)
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "expired"
        assert r["finished_at"] is not None
        assert (interrupted_of(counts), expired_of(counts)) == (0, 1)

    scenario(db_url, body)


def test_sweep_leaves_a_young_due_errand_due(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        age_created(w.url, eid, 100)
        counts = await w.errands.sweep(300, 600)
        assert row(w.url, eid)["state"] == "due"
        assert (interrupted_of(counts), expired_of(counts)) == (0, 0)

    scenario(db_url, body)


def test_sweep_counts_each_kind_and_leaves_finished_errands_alone(db_url: str) -> None:
    async def body(w: World) -> None:
        stuck = [(await w.owed_claimed())[0] for _ in range(2)]
        for e in stuck:
            age_claimed(w.url, e, 900)
        done, attempt = await w.owed_claimed()
        await w.errands.finish(done, attempt, "did it")
        age_created(w.url, done, 900)
        age_claimed(w.url, done, 900)
        given, given_attempt = await w.owed_claimed()
        await w.errands.give_up(given, given_attempt, "refused")
        age_created(w.url, given, 900)
        age_claimed(w.url, given, 900)
        old = [await w.owe() for _ in range(3)]
        for e in old:
            age_created(w.url, e, 900)
        counts = await w.errands.sweep(300, 600)
        assert (interrupted_of(counts), expired_of(counts)) == (2, 3)
        assert row(w.url, done)["state"] == "done" and row(w.url, done)["result"] == "did it"
        assert row(w.url, given)["reason"] == "refused"

    scenario(db_url, body)


def test_a_second_sweep_finds_nothing_more(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, _ = await w.owed_claimed()
        age_claimed(w.url, eid, 500)
        old = await w.owe()
        age_created(w.url, old, 900)
        await w.errands.sweep(300, 600)
        counts = await w.errands.sweep(300, 600)
        assert (interrupted_of(counts), expired_of(counts)) == (0, 0)
        assert row(w.url, eid)["reason"] == "interrupted"
        assert row(w.url, old)["reason"] == "expired"

    scenario(db_url, body)
