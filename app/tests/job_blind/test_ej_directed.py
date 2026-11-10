"""Directed tests for mutants the blind suite let through: sources differ, so the job's own skipping of a released
source cannot stand in for the batch cap or the end of the tick."""

import pytest
from ashley import logs
from ashley.inference.inference import InferenceUnavailable
from contract.conversations_support import events
from job_blind_support import TICK_FIELDS, World, owed_again, scenario


async def _three_sources(w: World) -> list[int]:
    return [await w.owe(source) for source in ("house", "search", "mail")]


def test_released_errands_of_other_sources_still_use_the_batch(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await _three_sources(w)
        w.model.play(owed_again("house"), owed_again("search"), owed_again("mail"))
        await w.tick()
        assert len(w.model.prompts) == w.config.batch == 2
        assert w.states(*ids) == ["due", "due", "due"]

    scenario(db_url, body)


def test_a_release_takes_its_source_out_of_the_tick(db_url: str) -> None:
    async def body(w: World) -> None:
        first, second = await w.owe_many(2)
        w.model.play(owed_again())
        await w.tick()
        assert len(w.model.prompts) == 1
        assert w.states(first, second) == ["due", "due"]

    scenario(db_url, body)


def test_inference_unavailable_ends_the_tick_whatever_the_other_sources(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await _three_sources(w)
        w.model.play(InferenceUnavailable("down"))
        await w.tick()
        assert len(w.model.prompts) == 1
        assert w.states(*ids) == ["due", "due", "due"]

    scenario(db_url, body)


def test_every_tick_log_carries_all_the_tick_fields(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    async def body(w: World) -> None:
        await w.owe()
        await w.tick()

    logs.setup()
    capsys.readouterr()
    scenario(db_url, body)
    [line] = events(capsys.readouterr().out, "errands.tick")
    assert all(f in line for f in TICK_FIELDS)
