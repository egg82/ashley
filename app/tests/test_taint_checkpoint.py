"""`Checkpoint.tainted` and `Inbound.taint` survive the checkpoint's JSON, so a resumed turn keeps its taint; a
checkpoint written before they existed loads untainted; `Saved` saves the first taint before the loop goes on and
never clears it."""

import json
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.inflight import Saved, begin
from ashley.channels.model import Taint
from ashley.channels.tool_loop import Progress
from ashley.conversations.inflight import Claim, InFlight, NullInFlight
from ashley.inference.model import Message, ToolResult
from contract.inference_support import settle
from hypothesis import given
from hypothesis import strategies as st
from inflight_blind.ifb_checkpoint_support import checkpoint


def tainted(by: str | None, origin: Taint | None = None) -> Checkpoint:
    base = checkpoint()
    return replace(base, inbound=replace(base.inbound, taint=origin), tainted=by)


ORIGINS: list[Taint | None] = [None, "watch", "stranger", "inherited", "pasted"]


@given(st.sampled_from(ORIGINS), st.sampled_from([None, "look_up", "webhook"]))
def test_the_origin_and_the_tainting_tool_round_trip(origin: Taint | None, by: str | None) -> None:
    got = loads(dumps(tainted(by, origin)))
    assert got.tainted == by and got.inbound.taint == origin


def test_a_result_keeps_its_outside_through_the_json() -> None:
    base = checkpoint()
    done = {r.call_id: r for r in (ToolResult("a", "x", outside=True), ToolResult("b", "x", outside=False),
                                   ToolResult("c", "x"))}
    got = loads(dumps(replace(base, progress=replace(base.progress, done=done))))
    assert [got.progress.done[i].outside for i in "abc"] == [True, False, None]


def test_a_checkpoint_from_before_the_taint_loads_untainted() -> None:
    raw = json.loads(dumps(checkpoint()))
    del raw["tainted"], raw["inbound"]["taint"]
    got = loads(json.dumps(raw))
    assert got.tainted is None and got.inbound.taint is None


def test_an_origin_that_is_not_one_is_refused() -> None:
    raw = json.loads(dumps(checkpoint()))
    raw["inbound"]["taint"] = "friend"
    with pytest.raises(ValueError):
        loads(json.dumps(raw))


class Keeping(NullInFlight):
    """Keeps each saved text."""

    def __init__(self) -> None:
        self.saved: list[str] = []

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        self.saved.append(checkpoint)
        return Claim(said_id, conversation_id, "h")

    async def save(self, claim: Claim, checkpoint: str) -> None:
        self.saved.append(checkpoint)


@pytest.fixture
def kept() -> Generator[Keeping]:
    store = Keeping()
    services.register(InFlight, store)
    yield store
    services.unregister(InFlight)


def test_the_first_tainting_tool_is_saved_and_a_second_changes_nothing(kept: Keeping) -> None:
    async def scenario() -> None:
        work = await begin(checkpoint().inbound, checkpoint())
        assert isinstance(work, Saved) and work.taint is None
        assert await work.tainted("look_up") is True
        assert loads(kept.saved[-1]).tainted == "look_up"
        count = len(kept.saved)
        assert await work.tainted("git_tree") is False
        assert len(kept.saved) == count and work.taint == "look_up"
    settle(scenario())


def test_a_turn_started_tainted_is_not_tainted_again_by_a_read(kept: Keeping) -> None:
    async def scenario() -> None:
        work = await begin(checkpoint().inbound, tainted("stranger", "stranger"))
        assert await work.tainted("look_up") is False
        assert work.taint == "stranger"
    settle(scenario())


def test_a_resumed_runner_starts_with_the_taint_the_checkpoint_had(kept: Keeping) -> None:
    async def scenario() -> None:
        work = await begin(checkpoint().inbound, checkpoint())
        await work.tainted("claude_read")
        resumed = Saved(Claim(77, 5, "other"), loads(kept.saved[-1]))
        assert resumed.taint == "claude_read" and await resumed.tainted("look_up") is False
    settle(scenario())


def test_progress_and_messages_are_untouched_by_the_taint() -> None:
    c = tainted("look_up")
    assert loads(dumps(c)).progress == c.progress == Progress((Message("person", "turn on the lamp"),), 0, 0)


def test_a_turn_that_is_not_checkpointed_keeps_its_taint_in_memory() -> None:
    async def scenario() -> None:
        base = checkpoint()
        work = await begin(replace(base.inbound, later=False), replace(base, tainted="watch"))
        assert not isinstance(work, Saved) and work.taint == "watch"
        assert await work.tainted("look_up") is False
        fresh = await begin(replace(base.inbound, later=False), base)
        assert await fresh.tainted("look_up") is True and fresh.taint == "look_up"
    settle(scenario())
