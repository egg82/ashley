"""What a turn tells the open screens through Live: thinking from the start, idle at the end (after a held answer, not
at the held reply), both for one turn token; shown to the household from a shared channel and to the person alone from
their own; a stored turn announced on an owner's thread only; and a web chat's held answer stored, never queued."""

import asyncio
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.outbox import Outbox
from ashley.channels.respond import RespondUnavailable, respond
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.reply import Reply
from ashley.live.events import HerState, Shown, ThreadTurn
from ashley.live.live import Live
from later_support import FakeOutbox, until
from live_support import FakeLive
from respond_support import ALANA, HOME, Fakes, inbound, wired as wired

REPLY = Reply(spoken="Done.", text="Done!")
CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")


@pytest.fixture
def live() -> Generator[FakeLive]:
    made = FakeLive()
    services.register(Live, made)
    yield made
    services.unregister(Live)


@pytest.fixture
def outbox() -> Generator[FakeOutbox]:
    made = FakeOutbox()
    services.register(Outbox, made)
    yield made
    services.unregister(Outbox)


def web(**changes: object) -> Inbound:
    return replace(inbound(thread=f"person:{ALANA.id}:web", kind="chat", shared=False, speaker_id=ALANA.id),
                   audience="owner", place=None, **changes)


def states(live: FakeLive) -> list[tuple[str, str, Shown]]:
    return [(e.turn, e.state, e.shown) for e in live.published if isinstance(e, HerState)]


def test_a_shared_channels_turn_is_thinking_then_idle_for_the_household_and_announces_no_thread(
        wired: Fakes, live: FakeLive) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound()))
    (turn, first, shown), (again, last, _) = states(live)
    assert (first, last, turn == again, shown) == ("thinking", "idle", True, Shown(HOME.id, None))
    assert not [e for e in live.published if isinstance(e, ThreadTurn)]


def test_a_devices_screen_is_told_of_each_stored_turn_on_its_thread_and_no_person_is(
        wired: Fakes, live: FakeLive) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(replace(inbound(), device_id=7)))
    screen = Shown(HOME.id, None, 7)
    assert [e for e in live.published if isinstance(e, ThreadTurn)] == [ThreadTurn(screen, "device:7")] * 2
    assert {shown for _, _, shown in states(live)} == {Shown(HOME.id, None)}


def test_a_persons_own_channel_is_shown_to_them_alone_with_both_stored_turns(wired: Fakes, live: FakeLive) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(web()))
    mine = Shown(HOME.id, ALANA.id)
    assert {shown for _, _, shown in states(live)} == {mine}
    assert [e for e in live.published if isinstance(e, ThreadTurn)] == [ThreadTurn(mine, f"person:{ALANA.id}:web")] * 2
    assert [type(e).__name__ for e in live.published] == ["HerState", "ThreadTurn", "ThreadTurn", "HerState"]


def test_a_turn_that_fails_still_ends_idle(wired: Fakes, live: FakeLive) -> None:
    wired.inference.script = [InferenceUnavailable("down")]
    with pytest.raises(RespondUnavailable):
        asyncio.run(respond(inbound()))
    assert [s for _, s, _ in states(live)] == ["thinking", "idle"]


def test_an_empty_message_tells_no_one(wired: Fakes, live: FakeLive) -> None:
    with pytest.raises(ValueError):
        asyncio.run(respond(inbound(text=" ")))
    assert live.published == []


def test_a_held_web_reply_stays_thinking_until_its_answer_is_stored_and_never_queues_it(
        wired: Fakes, live: FakeLive, outbox: FakeOutbox) -> None:
    wired.inference.script = [CHECKING, REPLY]

    async def scenario() -> list[str]:
        out = await respond(web(later=True, later_by="turn"))
        assert out.follows and [s for _, s, _ in states(live)] == ["thinking"]
        await until(lambda: len(states(live)) == 2)
        return [t.author for t in wired.conversations.convs[out.conversation_id].turns]

    assert asyncio.run(scenario()) == ["person", "ashley", "ashley"]
    assert [s for _, s, _ in states(live)] == ["thinking", "idle"] and outbox.added == []
    assert len([e for e in live.published if isinstance(e, ThreadTurn)]) == 3


def test_a_held_reply_on_an_outbox_channel_still_queues_its_answer(
        wired: Fakes, live: FakeLive, outbox: FakeOutbox) -> None:
    wired.inference.script = [CHECKING, REPLY]

    async def scenario() -> None:
        await respond(replace(inbound(), later=True))
        await until(lambda: len(states(live)) == 2)

    asyncio.run(scenario())
    assert len(outbox.added) == 1


def started_by_the_server(**changes: object) -> Inbound:
    return replace(web(), unprompted=True, author="household", watched=True, **changes)


def test_a_turn_the_server_started_is_thinking_then_idle_for_its_person_with_no_page_send(
        wired: Fakes, live: FakeLive) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(started_by_the_server()))
    (turn, first, shown), (again, last, _) = states(live)
    assert (first, last, turn == again, shown) == ("thinking", "idle", True, Shown(HOME.id, ALANA.id))


def test_a_turn_the_server_started_that_fails_still_ends_idle(wired: Fakes, live: FakeLive) -> None:
    wired.inference.script = [InferenceUnavailable("down")]
    with pytest.raises(RespondUnavailable):
        asyncio.run(respond(started_by_the_server()))
    assert [s for _, s, _ in states(live)] == ["thinking", "idle"]
