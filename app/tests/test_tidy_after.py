"""Which turns set the tidy pass going: a known person's turn on a bench (its own talk, or the bench its page moved to),
and no other."""

import asyncio
from dataclasses import replace

from ashley import services
from ashley.channels import bench_after
from ashley.channels.model import Inbound, on_bench
from ashley.people.model import Person
from ashley.tidy.tidy import Tidy
from ashley.channels.respond import respond
from ashley.inference.reply import Reply
from respond_support import ALANA, Fakes, inbound, wired as wired
from tidy_support import RecordingTidy


async def settle(tidy: RecordingTidy) -> list[int]:
    """The benches the pass asked about, once the tasks the turn started have run."""
    for _ in range(5):
        await asyncio.sleep(0)
    return tidy.asked


def started(inbound: Inbound, speaker: Person | None) -> list[int]:
    async def go() -> list[int]:
        tidy = RecordingTidy()
        services.register(Tidy, tidy)
        bench_after.tidy(inbound, speaker)
        return await settle(tidy)

    return asyncio.run(go())


def test_a_turn_on_a_benchs_own_talk_sets_the_pass_going_for_that_bench() -> None:
    assert started(on_bench(10, ALANA.id, 6, "hi"), ALANA) == [6]


def test_a_turn_whose_page_moved_to_a_bench_sets_it_going_for_that_bench() -> None:
    chat = replace(on_bench(10, ALANA.id, 6, "hi"), bench_id=None, moved_to=9)
    assert started(chat, ALANA) == [9]


def test_a_turn_off_any_bench_or_by_nobody_known_sets_nothing_going() -> None:
    chat = replace(on_bench(10, ALANA.id, 6, "hi"), bench_id=None)
    assert started(chat, ALANA) == [] and started(on_bench(10, None, 6, "hi"), None) == []


def test_her_answer_on_a_benchs_talk_sets_the_pass_going_and_a_chat_answer_does_not(wired: Fakes) -> None:
    talk = replace(inbound("fix the note", thread="bench:6", speaker_id=ALANA.id, kind="brainstorm"), audience="owner",
                   shared=False, place=None, channel="web", later=True, later_by="turn", bench_id=6, on_page=True)
    chat = replace(talk, thread="person:1:web", kind="chat", bench_id=None)

    async def go() -> tuple[list[int], list[int]]:
        tidy = RecordingTidy()
        services.register(Tidy, tidy)
        wired.inference.script = [Reply(spoken="Done.", text="Done.")]
        await respond(chat)
        after_chat = list(await settle(tidy))
        wired.inference.script = [Reply(spoken="Done.", text="Done.")]
        await respond(talk)
        return after_chat, await settle(tidy)

    assert asyncio.run(go()) == ([], [6])
