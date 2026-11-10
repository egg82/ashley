"""A reply's copy to the phone survives a kill (`decisions.md`, "Work in flight survives its pod"): a voice turn whose
runner is killed as it stores her answer is resumed by another runner, and the speaker's phone gets the text once.
Postgres is real (Conversations, `InFlight`, `Outbox`); the model and the people are fakes."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Later, Outbox, Pushed
from ashley.channels.push.subscriptions import Subscription, Subscriptions
from ashley.channels.respond import respond
from ashley.conversations.inflight import Claim, InFlight, Orphan
from ashley.conversations.model import AgreedOutcome, NewTurn, Turn
from ashley.inference.reply import Reply
from contract.conversations_support import run
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.test_inflight_resume import CLAIM_S, World, sweep
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world
from contract.test_inflight_resume_channels import SATELLITE, stores
from push_support import FakeSubscriptions, browser

LIST = Reply(spoken="I've put it on your phone.", text="1. Ramen\n2. Saffron Table", to_phone=True)


def spoken(world: World) -> Inbound:
    return Inbound(household_id=world.who.household_id, thread=f"device:{SATELLITE}", text="where can we eat",
                   kind="command", medium="spoken", audience="household", speaker_id=world.who.id, shared=True,
                   place="kitchen", channel="voice", later=True)


@dataclass
class Stalled(Outbox):
    """The real outbox, except that storing an answer waits forever once `stall` is set: the runner is killed there."""

    real: Outbox
    reached: asyncio.Event = field(default_factory=asyncio.Event)
    stall: bool = True

    async def add(self, household_id: int, thread: str, outbound: Outbound) -> int:
        return await self.real.add(household_id, thread, outbound)

    async def take(self, prefix: str) -> list[Later]:
        return await self.real.take(prefix)

    async def answer(self, claim: Claim, turn: NewTurn, pushed: Sequence[Pushed],
                     after: Callable[[Turn], str] | None = None) -> Turn:
        if self.stall:
            self.reached.set()
            await asyncio.Event().wait()
        return await self.real.answer(claim, turn, pushed, after)


class Stalling(InFlight):
    """Delegates to the real `InFlight`; `finish` waits forever while `stalled.stall` is set."""

    def __init__(self, real: InFlight, stalled: Stalled) -> None:
        self.real, self.stalled = real, stalled

    @property
    def claim_s(self) -> float:
        return self.real.claim_s

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        return await self.real.begin(conversation_id, said_id, checkpoint)

    async def save(self, claim: Claim, checkpoint: str) -> None:
        await self.real.save(claim, checkpoint)

    async def renew(self, claim: Claim) -> None:
        await self.real.renew(claim)

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        return await self.real.said(claim, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        if self.stalled.stall:
            self.stalled.reached.set()
            await asyncio.Event().wait()
        return await self.real.finish(claim, turn, after)

    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        await self.real.agreed(claim, outcome)

    async def drop(self, claim: Claim) -> bool:
        return await self.real.drop(claim)

    async def orphaned(self, limit: int) -> list[Orphan]:
        return await self.real.orphaned(limit)

    async def working(self, conversation_id: int) -> frozenset[int]:
        return await self.real.working(conversation_id)


def test_a_kill_as_her_answer_is_stored_leaves_the_phone_one_copy_after_the_resume(world: World) -> None:
    world.first.inference.script = [LIST]
    world.second.inference.script = [LIST]
    subscriptions = FakeSubscriptions()
    subscriptions.rows.append(Subscription(1, world.who.household_id, world.who.id, browser(1)))
    services.register(Subscriptions, subscriptions)
    phone: list[Later] = []
    device: list[Later] = []

    async def go() -> None:
        async with stores(world) as outbox:
            stalled = Stalled(outbox)
            services.register(Outbox, stalled)
            services.register(InFlight, Stalling(services.get(InFlight), stalled))
            world.as_pod(world.first)
            turn = asyncio.create_task(respond(spoken(world)))
            await asyncio.wait_for(stalled.reached.wait(), 5)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            stalled.stall = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1
            phone.extend(await outbox.take("push:"))
            device.extend(await outbox.take("device:"))

    try:
        run(go())
    finally:
        services.unregister(Subscriptions)
    assert [t.outbound.body for t in phone] == [LIST.text]
    assert [t.outbound.body for t in device] == [LIST.spoken]
    assert world.hers() == [LIST.text]
