"""A tick claims and runs up to `batch` errands, oldest first, and no more."""

from ashley.inference.inference import InferenceUnavailable
from dataclasses import replace
from job_blind_support import CONF, GOOD, World, owed_again, scenario


def test_a_tick_runs_at_most_batch_errands(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await w.owe_many(CONF.batch + 3)
        await w.tick()
        assert w.states(*ids) == ["done"] * CONF.batch + ["due"] * 3
        assert len(w.model.prompts) == CONF.batch
        assert len(w.errands.named("finish")) == CONF.batch

    scenario(db_url, body)


def test_the_next_tick_takes_the_next_batch(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await w.owe_many(2 * CONF.batch + 1)
        await w.tick()
        await w.tick()
        assert w.states(*ids) == ["done"] * (2 * CONF.batch) + ["due"]

    scenario(db_url, body)


def test_fewer_due_than_batch_runs_them_all_and_stops(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await w.owe_many(1)
        await w.tick()
        assert w.states(*ids) == ["done"]
        assert len(w.model.prompts) == 1

    scenario(db_url, body)


def test_the_oldest_errand_is_run_first(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await w.owe_many(CONF.batch + 1)
        await w.tick()
        assert [args[0] for args in w.errands.named("finish")] == ids[:CONF.batch]

    scenario(db_url, body)


def test_batch_comes_from_the_config(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await w.owe_many(5)
        await w.tick()
        assert w.states(*ids) == ["done"] * 4 + ["due"]

    scenario(db_url, body, replace(CONF, batch=4))


def test_a_released_errand_still_counts_toward_the_batch(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await w.owe_many(CONF.batch + 1)
        w.model.play(*[owed_again()] * 10)
        await w.tick()
        assert len(w.model.prompts) <= CONF.batch
        assert w.states(ids[-1]) == ["due"]

    scenario(db_url, body)


def test_a_tick_with_inference_down_makes_one_run_however_large_the_batch(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe_many(3)
        w.model.play(InferenceUnavailable("down"), GOOD, GOOD)
        await w.tick()
        assert len(w.model.prompts) == 1

    scenario(db_url, body, replace(CONF, batch=3))
