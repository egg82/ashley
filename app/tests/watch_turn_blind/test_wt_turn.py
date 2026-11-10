"""The turn a watch wake starts (`watch_turn`, which generalises `herdr_turn`): unprompted, so Initiative decides from
`worth_saying`; on the talk of the bench that armed the watch while it is open, else the person's phone thread; the
stored message the household's, from fields alone; her brief only the turn's note (the kind's note for the change, the
series and since, whether the watch ended); tools by `Reminder.tools`' rule, except that a hand-off watch keeps the
thread's."""

import re
from datetime import UTC, datetime

import pytest
from ashley.channels.unprompted import QUIET
from contract.conversations_support import run
from contract.test_inflight_resume import World
from wb_runner_support import DONE, SILENT, call, sweep
from watch_turn_blind_support import LABEL, ReadsAndChanges, Rig, messages_text, rig, tool_names

ENDED = re.compile(r"ended|no longer watch", re.I)


async def told(r: Rig, world: World, watch_id: int, status: str = "done", seq: int = 2,
               ends: str | None = None) -> str:
    """Wake the watch, run the sweep and return the text her model was sent for it."""
    before = len(world.first.inference.prompts)
    await r.woke(watch_id, status=status, seq=seq, ends=ends)
    await sweep()
    assert len(world.first.inference.prompts) > before
    return messages_text(world.first.inference.prompts[before])


def test_it_runs_on_the_talk_of_the_bench_that_armed_the_watch_while_that_bench_is_open(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            bench = await r.bench()
            await r.woke(await r.armed(bench_id=bench))
            await sweep()
            [(author, _, _), (hers, text, _)] = r.turns_on(f"bench:{bench}")
            assert (author, hers, text) == ("household", "ashley", DONE.text)
            assert r.turns_on(f"push:{world.who.id}") == []

    run(go())


def test_a_closed_bench_or_none_sends_it_to_the_persons_phone_thread(world: World) -> None:
    world.first.inference.script = [DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            bench = await r.bench()
            await r.close_bench(bench)
            await r.woke(await r.armed(bench_id=bench))
            await r.woke(await r.armed(target="other-session", bench_id=None), status="blocked")
            await sweep()
            assert r.turns_on(f"bench:{bench}") == []
            assert len(r.turns_on(f"push:{world.who.id}")) == 4

    run(go())


def test_the_turn_is_unprompted_so_a_reply_set_not_worth_saying_queues_nothing(world: World) -> None:
    world.first.inference.script = [SILENT]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            await r.woke(await r.armed())
            await sweep()
            assert r.s.queued() == 0

    run(go())
    assert world.hers() == [QUIET]


def test_a_reply_worth_saying_goes_out_on_the_phone_thread(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            await r.woke(await r.armed())
            await sweep()
            assert r.s.queued() == 1

    run(go())


def test_the_stored_message_is_the_households_written_from_label_and_status_alone(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            await r.woke(await r.armed(), status="blocked", seq=41)
            await sweep()
            [(text, _)] = r.household_turns()
            assert LABEL in text and "blocked" in text
            assert "claude_read" not in text and "{" not in text and "since" not in text

    run(go())


def test_her_brief_is_only_the_turns_note_and_is_never_stored(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            seen = await told(r, world, await r.armed())
            assert "claude_read" in seen
            assert all("claude_read" not in t for _, t, _ in r.turns_on(f"push:{world.who.id}"))

    run(go())


def test_a_block_and_a_finish_get_their_own_notes(world: World) -> None:
    world.first.inference.script = [DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            blocked = await told(r, world, await r.armed(target="a"), status="blocked")
            done = await told(r, world, await r.armed(target="b"), status="done")
            assert "dialog" in blocked and "dialog" not in done

    run(go())


def test_the_note_names_which_wake_in_the_series_this_is_and_since_when(world: World) -> None:
    world.first.inference.script = [DONE, DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            watch = await r.armed()
            first = await told(r, world, watch, status="done", seq=2)
            await told(r, world, watch, status="blocked", seq=3)
            third = await told(r, world, watch, status="done", seq=4)
            nth = re.compile(r"\b3\b|3rd|third", re.I)
            assert nth.search(third) and not nth.search(first)
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            assert today in first or today in third

    run(go())


def test_the_note_says_whether_the_watch_has_ended(world: World) -> None:
    world.first.inference.script = [DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            ongoing = await told(r, world, await r.armed(target="a"))
            ended = await told(r, world, await r.armed(target="b"), ends="until")
            assert ENDED.search(ended) and not ENDED.search(ongoing)

    run(go())


def test_a_paused_watch_tells_her_why_and_not_that_a_session_finished(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            await r.paused(await r.armed(), reason="not_connected")
            await sweep()
            seen = messages_text(world.first.inference.prompts[0])
            assert "not_connected" in seen or "connection" in seen.lower()

    run(go())


def test_with_no_tools_named_only_the_tools_that_read_are_offered(world: World) -> None:
    world.first.inference.script = [call("garage_open"), DONE]
    world.as_pod(world.first)
    tools = ReadsAndChanges()

    async def go() -> None:
        async with rig(world, tools) as r:
            await r.woke(await r.armed(tools=None))
            await sweep()

    run(go())
    names = tool_names(world.first.inference.prompts[0])
    assert "lamp_state" in names and not names & {"lamp_on", "garage_open"}
    assert tools.ran == []


def test_named_tools_are_the_only_tools_and_others_cannot_be_called(world: World) -> None:
    world.first.inference.script = [call("lamp_on"), call("garage_open", "c2"), DONE]
    world.as_pod(world.first)
    tools = ReadsAndChanges()

    async def go() -> None:
        async with rig(world, tools) as r:
            await r.woke(await r.armed(tools=("lamp_on",)))
            await sweep()

    run(go())
    names = tool_names(world.first.inference.prompts[0])
    assert "lamp_on" in names and not names & {"lamp_state", "garage_open"}
    assert [c.name for c in tools.ran] == ["lamp_on"]


@pytest.mark.parametrize("named", [None, ("lamp_on",)])
def test_a_hand_off_watch_keeps_the_threads_tools(world: World, named: tuple[str, ...] | None) -> None:
    world.first.inference.script = [call("garage_open"), DONE]
    world.as_pod(world.first)
    tools = ReadsAndChanges()

    async def go() -> None:
        async with rig(world, tools) as r:
            await r.woke(await r.armed(armed_by="handoff", tools=named))
            await sweep()

    run(go())
    assert {"lamp_state", "lamp_on", "garage_open"} <= tool_names(world.first.inference.prompts[0])
    assert [c.name for c in tools.ran] == ["garage_open"]


def test_the_turn_is_with_the_person_on_a_thread_that_is_theirs(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with rig(world) as r:
            await r.woke(await r.armed())
            await sweep()
            assert [a for a, _, _ in r.turns_on(f"push:{world.who.id}")] == ["household", "ashley"]

    run(go())
