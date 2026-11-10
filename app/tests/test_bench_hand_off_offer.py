"""`bench_hand_off` is offered only on a bench's talk, where the reply reaches the speaker alone and nobody woke the
turn; elsewhere it is absent (`channels.turn_tools.sources`)."""

import asyncio
from dataclasses import replace

from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn, hands_off, sources
from ashley.channels.wake import watch_turn
from ashley.connections.connections import Connections
from ashley.criteria.record import Change
from ashley.runs.sandbox import Sandbox
from ashley.senses.wakes import WatchWake
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.tools import Catalogue, Tools
from ashley.watches import bench_job
from ashley.watches.rows import changed_wake
from bench_run_support import Box
from money_support import HeldConnections
from watch_job_support import NOW, watch as a_watch

BENCH = Inbound(household_id=1, thread="bench:3", text="hi", kind="brainstorm", medium="text", audience="owner",
                speaker_id=7, shared=False, place=None, channel="web", later=True, later_by="turn", bench_id=3)


class NoHouse(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError


def offered(inbound: Inbound) -> bool:
    services.register(Connections, HeldConnections())
    return "jobs" in sources(inbound, turn=(1, 2), conversation_id=1)


def test_it_is_offered_on_a_bench_turn_the_speaker_hears_alone() -> None:
    assert offered(BENCH) and hands_off(BENCH)


def test_it_is_absent_on_a_woken_turn_a_shared_one_a_device_a_stranger_and_off_a_bench() -> None:
    assert not offered(replace(BENCH, unprompted=True))
    assert not offered(replace(BENCH, audience="household", shared=True))
    assert not offered(replace(BENCH, device_id=3))
    assert not offered(replace(BENCH, speaker_id=None))
    assert not offered(replace(BENCH, bench_id=None, thread="person:7:web", kind="chat"))


def test_the_wake_when_a_hand_off_settles_can_change_and_run_the_bench_but_not_hand_off_again() -> None:
    """Its note tells her to act on the results in that turn, which rests on these tools being there."""
    settled = Change("3", "changed", {"settled": False, "blocked": 0}, {"settled": True, "blocked": 0})
    wake = WatchWake(1, 7, 1, "changed", changed_wake(1, NOW, False, (settled,)))
    watch = replace(a_watch(kind=bench_job.NAME, target="3", person=7), bench_id=3, armed_by="handoff")
    woken = watch_turn.inbound(9, watch, wake, on_bench=True)
    assert (woken.note or "").startswith(bench_job.SETTLED_NOTE)
    services.register(Connections, HeldConnections())
    services.register(Tools, NoHouse())
    services.register(Sandbox, Box())
    try:
        names = {s.name for s in asyncio.run(for_turn(woken, (20, 30)).catalogue()).specs}
    finally:
        services.unregister(Sandbox)
        services.unregister(Tools)
    assert {"bench_edit", "bench_undo", "bench_run"} <= names and "bench_hand_off" not in names
