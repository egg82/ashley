"""`Steps.changed`: true once a change began on the turn, kept in the checkpoint (so a runner that resumes the turn
knows), never set by a read; a checkpoint written before it existed loads unchanged."""

import json
from dataclasses import replace

from ashley import services
from ashley.channels.checkpoint import dumps, loads
from ashley.channels.inflight import Saved, begin
from ashley.conversations.inflight import Claim, InFlight, NullInFlight
from ashley.inference.model import ToolCall
from contract.inference_support import settle
from inflight_blind.ifb_checkpoint_support import checkpoint

CALL = ToolCall("c0", "add_item", {"item": "eggs"})


class Keeping(NullInFlight):
    def __init__(self) -> None:
        self.saved: list[str] = []

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        self.saved.append(checkpoint)
        return Claim(said_id, conversation_id, "h")

    async def save(self, claim: Claim, checkpoint: str) -> None:
        self.saved.append(checkpoint)


def test_a_saved_turn_is_unchanged_until_a_change_starts_and_a_resumed_runner_knows() -> None:
    store = Keeping()
    services.register(InFlight, store)
    try:
        async def scenario() -> None:
            work = await begin(checkpoint().inbound, checkpoint())
            assert isinstance(work, Saved) and not work.changed
            await work.starting(CALL)
            assert work.changed and loads(store.saved[-1]).changed
            assert Saved(Claim(77, 5, "other"), loads(store.saved[-1])).changed
        settle(scenario())
    finally:
        services.unregister(InFlight)


def test_a_turn_that_is_not_checkpointed_is_changed_once_a_change_starts() -> None:
    async def scenario() -> None:
        base = checkpoint()
        work = await begin(replace(base.inbound, later=False), base)
        assert not isinstance(work, Saved) and not work.changed
        await work.starting(CALL)
        assert work.changed
    settle(scenario())


def test_a_checkpoint_from_before_it_loads_unchanged() -> None:
    raw = json.loads(dumps(replace(checkpoint(), changed=True)))
    assert loads(json.dumps(raw)).changed
    del raw["changed"]
    assert not loads(json.dumps(raw)).changed
