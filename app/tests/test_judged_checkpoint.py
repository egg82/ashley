"""The action judge's verdicts survive the checkpoint's JSON and are saved by `Saved` before the call goes on, so a runner
that resumes the turn reads them back instead of judging again; a checkpoint written before they existed loads with none, and
a verdict that is not one is refused."""

import json
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.checkpoint import dumps, loads
from ashley.channels.inflight import Saved, Unsaved, begin
from ashley.conversations.inflight import Claim, InFlight, NullInFlight
from ashley.tools.action_judge import Verdict
from contract.inference_support import settle
from inflight_blind.ifb_checkpoint_support import checkpoint

RUN = Verdict("run", "asked_directly", "You asked for it.")
ASK = Verdict("ask", "recipient_unknown", "I don't know that address.")


class Keeping(NullInFlight):
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


def test_verdicts_round_trip_with_their_reason_and_explanation() -> None:
    got = loads(dumps(replace(checkpoint(), judged={"c1": RUN, "c2": ASK})))
    assert got.judged == {"c1": RUN, "c2": ASK}


def test_a_checkpoint_from_before_verdicts_loads_with_none() -> None:
    raw = json.loads(dumps(checkpoint()))
    del raw["judged"]
    assert loads(json.dumps(raw)).judged == {}


@pytest.mark.parametrize("bad", [["maybe", "unclear", "x"], ["run", "because", "x"], ["run"], "run", 3])
def test_a_verdict_that_is_not_one_is_refused(bad: object) -> None:
    raw = json.loads(dumps(checkpoint()))
    raw["judged"] = {"c1": bad}
    with pytest.raises(ValueError):
        loads(json.dumps(raw))


def test_a_verdict_is_saved_before_the_loop_goes_on_and_a_resumed_runner_reads_it(kept: Keeping) -> None:
    async def scenario() -> None:
        work = await begin(checkpoint().inbound, checkpoint())
        assert isinstance(work, Saved) and work.judgement("c1") is None
        await work.judged("c1", RUN)
        assert loads(kept.saved[-1]).judged == {"c1": RUN}
        resumed = Saved(Claim(77, 5, "other"), loads(kept.saved[-1]))
        assert resumed.judgement("c1") == RUN and resumed.judgement("c2") is None
        await resumed.judged("c2", ASK)
        assert loads(kept.saved[-1]).judged == {"c1": RUN, "c2": ASK}
    settle(scenario())


def test_a_turn_that_is_not_checkpointed_keeps_its_verdicts_in_memory() -> None:
    async def scenario() -> None:
        work = await begin(replace(checkpoint().inbound, later=False), checkpoint())
        assert isinstance(work, Unsaved)
        await work.judged("c1", ASK)
        assert work.judgement("c1") == ASK
    settle(scenario())
