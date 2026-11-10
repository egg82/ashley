"""A turn that began in chat and landed on a bench is that bench's running turn (`decisions.md`, "A message on a bench
steers the running turn"): a message on the bench while it runs starts no turn of its own and is handed to it, so the
bench gets one reply. Postgres is real (Conversations and `InFlight`); the model, tools and workshop are fakes."""

import asyncio
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.model import Inbound, Outbound
from ashley.channels.respond import respond
from ashley.inference.model import Message, ToolCall, ToolCalls
from ashley.live.live import Live
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.conversations_support import run, scalar
from contract.test_bench_steering import ANOTHER, SECOND, Hooked, Sends
from contract.test_inflight_resume import CLAIM_S, DONE, Pod, World, database, sweep, switch_on
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world
from live_support import FakeLive
from test_reply_follows_page import Shop

SAID = f"Alana just said: {SECOND}"


@pytest.fixture
def shop(world: World) -> Generator[Shop]:
    fake = Shop()
    services.register(Workshop, fake)
    services.register(Live, FakeLive())
    yield fake
    services.unregister(Workshop)
    services.unregister(Live)


def chat(world: World) -> Inbound:
    return replace(world.inbound(), later=True, later_by="turn", on_page=True)


def on_bench(world: World) -> Inbound:
    return replace(chat(world), thread="bench:9", kind="brainstorm", bench_id=9, text=SECOND, steers=True)


def move() -> ToolCalls:
    return ToolCalls((ToolCall("m", "move_page", {"to": "bench", "bench_id": 9, "aside": "Over to the bench."}),))


def talk(world: World) -> list[tuple[str, str]]:
    got = scalar(world.url, "SELECT coalesce(string_agg(author || ':' || text, '|' ORDER BY t.id), '') FROM turns t "
                            "JOIN conversation_threads c ON c.conversation_id = t.conversation_id "
                            "WHERE c.thread = 'bench:9'")
    return [(a, t) for a, t in (row.split(":", 1) for row in str(got).split("|") if row)]


def test_a_bench_message_while_a_turn_that_landed_there_runs_is_handed_to_it_and_the_bench_gets_one_reply(
        world: World, shop: Shop) -> None:
    tools = Sends()
    pod = Pod(Hooked(), tools)
    world.first = pod
    pod.inference.script = [move(), switch_on(), DONE, ANOTHER]
    seen: list[Outbound] = []

    async def second() -> None:
        seen.append(await respond(on_bench(world)))

    tools.during = second

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            await respond(chat(world))

    run(go())
    assert [(o.follows, o.body) for o in seen] == [(True, "")]
    handed = [e.text for e in pod.inference.prompts[2].messages if isinstance(e, Message)]
    assert handed[-1] == SAID
    assert talk(world) == [("person", chat(world).text), ("person", SECOND), ("ashley", DONE.text)]


def test_a_runner_killed_just_after_the_move_leaves_the_resumed_turn_the_benchs_running_turn(
        world: World, shop: Shop) -> None:
    world.first.tools.hang = True
    world.first.inference.script = [ToolCalls((*move().calls, *switch_on().calls))]
    tools = Sends()
    world.second = Pod(Hooked(), tools)
    world.second.inference.script = [switch_on("c2"), DONE, ANOTHER]
    seen: list[Outbound] = []

    async def second() -> None:
        seen.append(await respond(on_bench(world)))

    tools.during = second

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            turn = asyncio.create_task(respond(chat(world)))
            await asyncio.wait_for(world.first.tools.reached.wait(), 5)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    run(go())
    assert [(o.follows, o.body) for o in seen] == [(True, "")]
    assert talk(world) == [("person", chat(world).text), ("person", SECOND), ("ashley", DONE.text)]
