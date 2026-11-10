"""A voice turn whose reply goes to the speaker's phone, killed around the moment her answer is stored: after the
resume the phone has the text exactly once, never zero and never twice. Postgres is real (Conversations, `InFlight`,
`Outbox`); the model and the people are fakes."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pytest
from ashley import services
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Later, Outbox, Pushed
from ashley.channels.push.subscriptions import Subscription, Subscriptions
from ashley.channels.respond import respond
from ashley.conversations.inflight import Claim
from ashley.conversations.model import NewTurn, Turn
from ashley.inference.reply import Reply
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, World, sweep
from contract.test_inflight_resume_channels import SATELLITE, stores
from push_support import FakeSubscriptions, browser

LIST = Reply(spoken="It is on your phone.", text="1. Ramen\n2. Saffron Table", to_phone=True)


@dataclass
class Killing(Outbox):
    """The real outbox; `answer` is cut off inside its transaction (`mid`) or just after it committed."""

    real: Outbox
    mid: bool
    armed: bool = True

    async def add(self, household_id: int, thread: str, outbound: Outbound) -> int:
        return await self.real.add(household_id, thread, outbound)

    async def take(self, prefix: str) -> list[Later]:
        return await self.real.take(prefix)

    async def answer(self, claim: Claim, turn: NewTurn, pushed: Sequence[Pushed],
                     after: Callable[[Turn], str] | None = None) -> Turn:
        if not self.armed:
            return await self.real.answer(claim, turn, pushed, after)
        self.armed = False
        if self.mid:
            def cut(stored: Turn) -> str:
                task = asyncio.current_task()
                assert task is not None
                task.cancel()
                return after(stored) if after else ""
            return await self.real.answer(claim, turn, pushed, cut)
        done = await self.real.answer(claim, turn, pushed, after)
        me = asyncio.current_task()
        assert me is not None
        me.cancel()
        await asyncio.sleep(0)
        return done


def spoken(world: World) -> Inbound:
    return Inbound(household_id=world.who.household_id, thread=f"device:{SATELLITE}", text="where can we eat",
                   kind="command", medium="spoken", audience="household", speaker_id=world.who.id, shared=True,
                   place="kitchen", channel="voice", later=True)


async def kill_and_resume(world: World, mid: bool) -> tuple[list[Later], int]:
    world.first.inference.script = [LIST]
    world.second.inference.script = [LIST]
    async with stores(world) as outbox:
        services.register(Outbox, Killing(outbox, mid))
        world.as_pod(world.first)
        turn = asyncio.create_task(respond(spoken(world)))
        with pytest.raises(asyncio.CancelledError):
            await turn
        await asyncio.sleep(CLAIM_S * 1.5)
        world.as_pod(world.second)
        resumes = await sweep()
        return await outbox.take("push:"), resumes


@pytest.mark.parametrize("mid", [True, False], ids=["before commit", "after commit"])
def test_the_phone_gets_the_text_once_whenever_the_runner_is_killed(world: World, mid: bool) -> None:
    subscriptions = FakeSubscriptions()
    subscriptions.rows.append(Subscription(1, world.who.household_id, world.who.id, browser(1)))
    services.register(Subscriptions, subscriptions)
    got: list[tuple[list[Later], int]] = []

    async def go() -> None:
        got.append(await kill_and_resume(world, mid))

    try:
        run(go())
    finally:
        services.unregister(Subscriptions)
    phone, resumes = got[0]
    assert [t.outbound.body for t in phone] == [LIST.text]
    assert resumes == (1 if mid else 0), "a runner killed after the commit leaves nothing to resume"
    assert world.hers() == [LIST.text]
