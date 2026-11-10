"""The taint as the checkpoint stores it: `Checkpoint.tainted`, `Inbound.taint` inside its inbound, the JSON round trip,
a checkpoint an older pod saved, and `Steps.tainted`."""

import json
from dataclasses import replace

import psycopg
import pytest
from ashley.channels import checkpoint
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.inflight import Saved, begin
from ashley.channels.model import Inbound
from ashley.channels.tool_loop import NO_STEPS, Progress, Steps
from ashley.conversations.inflight import ClaimLost
from ashley.conversations.model import NewTurn
from ashley.inference.model import Message, SystemPrompt
from contract.conversations_support import run
from taint_fields_blind_world_support import World, stored, world


def a_checkpoint(**changes: object) -> Checkpoint:
    inbound = Inbound(1, "web:1", "hi", "chat", "text", "owner", 2, False, None, "web", later=True)
    base = Checkpoint(inbound, 10, 11, 2, {"default": SystemPrompt("s")}, Progress((Message("person", "hi"),), 0, 0))
    return replace(base, **changes)


def test_a_checkpoint_starts_untainted() -> None:
    assert a_checkpoint().tainted is None


@pytest.mark.parametrize("name", [None, "fetch"])
def test_the_tool_that_tainted_the_turn_survives_the_json(name: str | None) -> None:
    got = loads(dumps(a_checkpoint(tainted=name)))
    assert got.tainted == name
    assert got == a_checkpoint(tainted=name)


@pytest.mark.parametrize("origin", [None, "watch", "stranger"])
def test_the_origin_survives_the_json(origin: str | None) -> None:
    inbound = replace(a_checkpoint().inbound, taint=origin)
    assert loads(dumps(a_checkpoint(inbound=inbound))).inbound.taint == origin


def test_the_origin_and_the_tool_are_kept_apart() -> None:
    inbound = replace(a_checkpoint().inbound, taint="watch")
    got = loads(dumps(a_checkpoint(inbound=inbound, tainted="fetch")))
    assert (got.inbound.taint, got.tainted) == ("watch", "fetch")


def test_a_checkpoint_an_older_pod_saved_loads_untainted() -> None:
    raw = json.loads(dumps(a_checkpoint(tainted="fetch", inbound=replace(a_checkpoint().inbound, taint="watch"))))
    assert "tainted" in raw and "taint" in raw["inbound"], "control: the keys are the field names"
    del raw["tainted"]
    del raw["inbound"]["taint"]
    got = loads(json.dumps(raw))
    assert got.tainted is None and got.inbound.taint is None


def test_the_origin_is_still_there_for_the_line_that_tells_the_person_the_turn_ended() -> None:
    inbound = replace(a_checkpoint().inbound, taint="stranger")
    got = checkpoint.addressed(dumps(a_checkpoint(inbound=inbound)))
    assert got is not None and got[0].taint == "stranger"


def test_a_turn_that_is_not_saved_records_a_taint_as_nothing() -> None:
    async def go() -> None:
        assert not await Steps().tainted("fetch")
        assert not await NO_STEPS.tainted("fetch")

    run(go())


def test_saved_work_stores_the_tool_that_tainted_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            work = await begun(w)
            before = stored(db_url)
            assert before is not None and before.tainted is None
            await work.tainted("fetch")
            after = stored(db_url)
            assert after is not None and after.tainted == "fetch"
            assert work.checkpoint.tainted == "fetch"

    run(go())


def test_saved_work_keeps_the_rest_of_the_checkpoint_when_it_stores_a_taint(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            work = await begun(w)
            before = work.checkpoint
            await work.tainted("fetch")
            assert replace(work.checkpoint, tainted=None) == before

    run(go())


def test_a_runner_that_lost_the_turn_cannot_record_a_taint(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            work = await begun(w)
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute(b"UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'")
            assert len(await w.inflight.orphaned(10)) == 1, "control: another runner took the turn"
            with pytest.raises(ClaimLost):
                await work.tainted("fetch")
            kept = stored(db_url)
            assert kept is not None and kept.tainted is None

    run(go())


async def begun(w: World) -> Saved:
    conv = await w.conversations.for_thread(w.home, "web:1", "chat", [w.who])
    said = await w.conversations.add_turn(conv.id, NewTurn("person", "hi", w.who))
    saved = replace(a_checkpoint(), conversation_id=conv.id, said_id=said.id, speaker_id=w.who,
                    inbound=w.inbound())
    work = await begin(saved.inbound, saved)
    assert isinstance(work, Saved)
    return work
