"""What a tick does before it runs anything: it sweeps every tick; it reads the catalogue only when something is due;
it takes only errands whose source answers."""

from ashley.tools.tools import ToolsUnavailable
from job_blind_support import CONF, HOUSE, SEARCH, World, age_claimed, age_created, row, scenario, unreachable


def test_a_tick_sweeps_with_the_configured_ages(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.tick()
        assert w.errands.named("sweep") == [(CONF.claim_s, CONF.max_age_s)]

    scenario(db_url, body)


def test_every_tick_sweeps_again(db_url: str) -> None:
    async def body(w: World) -> None:
        for _ in range(3):
            await w.tick()
        assert len(w.errands.named("sweep")) == 3

    scenario(db_url, body)


def test_the_sweep_runs_before_anything_is_claimed(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        await w.tick()
        assert [n for n, _ in w.errands.calls][0] == "sweep"

    scenario(db_url, body)


def test_nothing_due_reads_no_catalogue_and_claims_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.tick()
        assert w.tools.reads == 0
        assert w.errands.named("claim") == []
        assert w.model.prompts == []

    scenario(db_url, body)


def test_errands_that_are_not_due_do_not_count_as_due(db_url: str) -> None:
    async def body(w: World) -> None:
        done = await w.owe()
        await w.errands.claim({HOUSE}, 1_000)
        await w.errands.finish(done, 1, "did it")
        running = await w.owe()
        await w.errands.claim({HOUSE}, 1_000)
        gone = await w.owe()
        await w.errands.claim({HOUSE}, 1_000)
        await w.errands.give_up(gone, 1, "refused")
        w.forget_calls()
        await w.tick()
        assert w.tools.reads == 0 and w.errands.named("claim") == []
        assert row(w.url, running)["state"] == "running"

    scenario(db_url, body)


def test_an_errand_the_sweep_expires_is_not_due_so_the_catalogue_is_not_read(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        age_created(w.url, eid, CONF.max_age_s + 100)
        await w.tick()
        assert row(w.url, eid)["state"] == "given_up" and row(w.url, eid)["reason"] == "expired"
        assert w.tools.reads == 0 and w.model.prompts == []

    scenario(db_url, body)


def test_a_running_errand_past_claim_s_is_interrupted_and_not_retaken(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        await w.errands.claim({HOUSE}, 1_000)
        age_claimed(w.url, eid, CONF.claim_s + 100)
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "interrupted" and r["attempts"] == 1
        assert w.model.prompts == [] and w.tools.ran == []

    scenario(db_url, body)


def test_when_something_is_due_the_catalogue_is_read_once(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe_many(2)
        await w.tick()
        assert w.tools.reads == 1

    scenario(db_url, body)


def test_the_catalogue_is_read_once_even_when_nothing_answers(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        w.tools.offer = unreachable(HOUSE)
        await w.tick()
        assert w.tools.reads == 1

    scenario(db_url, body)


def test_no_catalogue_means_no_source_answers(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.tools.offer = ToolsUnavailable("down")
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "due" and r["attempts"] == 0
        assert w.model.prompts == [] and w.tools.ran == []
        assert len(w.errands.named("sweep")) == 1

    scenario(db_url, body)


def test_an_unreachable_source_is_not_claimed_and_its_errand_stays_due(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe(HOUSE)
        w.tools.offer = unreachable(HOUSE)
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "due" and r["attempts"] == 0 and r["claimed_at"] is None
        assert w.model.prompts == []
        assert all(HOUSE not in answering for answering, _ in w.errands.named("claim"))

    scenario(db_url, body)


def test_only_the_errand_whose_source_answers_is_run(db_url: str) -> None:
    async def body(w: World) -> None:
        down = await w.owe(HOUSE)
        up = await w.owe(SEARCH)
        w.tools.offer = unreachable(HOUSE)
        await w.tick()
        assert w.states(down, up) == ["due", "done"]
        assert len(w.model.prompts) == 1
        assert all(HOUSE not in answering for answering, _ in w.errands.named("claim"))

    scenario(db_url, body)


def test_an_older_errand_of_an_unreachable_source_does_not_block_a_younger_one(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe(HOUSE)
        later = await w.owe(SEARCH)
        w.tools.offer = unreachable(HOUSE)
        await w.tick()
        assert row(w.url, later)["state"] == "done"

    scenario(db_url, body)


def test_a_source_that_is_not_listed_unreachable_answers(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = [await w.owe(HOUSE), await w.owe(SEARCH)]
        await w.tick()
        assert w.states(*ids) == ["done", "done"]

    scenario(db_url, body)


def test_claim_is_asked_for_the_configured_max_age(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        await w.tick()
        assert {age for _, age in w.errands.named("claim")} == {CONF.max_age_s}

    scenario(db_url, body)
