"""The session sense as a watch, over a real database and the real bridge program's session list: a session she handed
work to wakes her once when it moves into `blocked`, `done` or `idle`, never again for the same state, never for someone
looking at a finished one, never for a session she did not hand work to, keeps being watched past a finish, and
survives a restart or the lease moving between sites with neither a replay nor a loss."""

import asyncio
import pytest
from ashley import logs, services
from ashley.channels.wake import watch_turn
from ashley.criteria import condition
from ashley.senses.wakes import Wakes, WatchWake
from ashley.watches import job
from ashley.watches.config import CONFIG
from ashley.watches.diff import diff
from ashley.watches.judge import judge
from ashley.watches.model import Quiet, Woke
from ashley.watches.watches import Watches
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import events, run, scalar
from watch_job_support import session, watch
from watch_session_support import states, told, watching

KIND = CONFIG.kinds["claude_session"]


@pytest.mark.parametrize("recorded,seen,expected", [
    (("idle", 5), ("done", 6), True), (("working", 6), ("blocked", 7), True), (("done", 6), ("done", 6), False),
    (("blocked", 7), ("blocked", 7), False), (("idle", 5), ("working", 6), False), (("idle", 5), ("idle", 6), True),
    (("idle", 5), ("unknown", 6), False), (("working", 6), ("done", 8), True), (("working", 6), ("idle", 7), True),
    (("done", 6), ("idle", 7), False), (("done", 900), ("idle", 3), False), (("idle", 7), ("idle", 7), False),
    (("done", 9), ("done", 10), True), (("working", 900), ("done", 3), True),
    (("done", 900), ("done", 3), True)])   # herdr restarted and finished again: the count differs, so it is told
def test_a_transition_is_a_finish_or_a_block_not_yet_acted_on(
        recorded: tuple[str, int], seen: tuple[str, int], expected: bool) -> None:
    check = judge(session(*seen), watch(baseline=session(*recorded)))
    assert isinstance(check, (Woke, Quiet)) and isinstance(check, Woke) is expected


def test_the_default_when_is_the_one_the_session_sense_had() -> None:
    changes = diff(session("done", 5), session("idle", 6))
    assert not condition.satisfied(KIND.when, changes)


def test_idle_to_working_to_done_wakes_once_and_repeated_checks_do_not(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("idle", 1000)
            for status, seq, woke in (("idle", 1000, 0), ("working", 1001, 0), ("working", 1001, 0),
                                      ("done", 1002, 1), ("done", 1002, 0), ("done", 1002, 0)):
                w.bridge.state(status, seq)
                assert (await w.tick())["woke"] == woke, (status, seq)
                await w.settle()
            [(event, status)] = told(db_url)
            assert status == "done" and event.startswith("watch:") and states(db_url) == [("done", 1002)]
    run(go())


def test_blocked_wakes_once_and_the_session_is_still_watched(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.state("blocked", 1002)
            woke: list[int] = []
            for _ in range(3):
                woke.append((await w.tick())["woke"])
                await w.settle()
            assert woke == [1, 0, 0] and states(db_url) == [("blocked", 1002)]
            w.bridge.state("working", 1003)
            assert (await w.tick())["woke"] == 0
            w.bridge.state("done", 1004)
            assert (await w.tick())["woke"] == 1
            assert [s for _, s in told(db_url)] == ["blocked", "done"] and states(db_url) == [("done", 1004)]
    run(go())


def test_a_finished_session_that_wakes_again_on_its_own_wakes_again_and_a_look_does_not(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            for status, seq, woke in (("done", 1002, 1),    # finished, and she was told
                                      ("idle", 1003, 0),    # the person looked at it
                                      ("working", 1004, 0), ("done", 1005, 1),   # a Monitor returned, unprompted
                                      # the baseline is still the last finish, so a finish the person watched is
                                      # only a look at it
                                      ("working", 1006, 0), ("idle", 1007, 0), ("idle", 1007, 0)):
                w.bridge.state(status, seq)
                assert (await w.tick())["woke"] == woke, (status, seq)
                await w.settle()
            assert [s for _, s in told(db_url)] == ["done", "done"] and states(db_url) == [("done", 1005)]
    run(go())


def test_sessions_she_did_not_hand_work_to_never_wake_her(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            w.bridge.state("done", 1002)   # the list also holds sessions the person runs, one of them done
            assert (await w.tick())["due"] == 0 and told(db_url) == [] and w.bridge.asked == 0
            await w.arm(target="not-in-the-list")
            counts = await w.tick()
            assert counts["woke"] == 0 and told(db_url) == [] and w.bridge.asked == 1
    run(go())


def test_a_restart_with_the_state_stored_acts_on_nothing_old(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.state("blocked", 1002)
            assert (await w.tick())["woke"] == 1
            await w.settle()
        async with watching(db_url, w) as restarted:   # a new process: nothing in memory, the state in Postgres
            restarted.bridge.state("blocked", 1002)
            assert (await restarted.tick())["woke"] == 0 and len(told(db_url)) == 1
    run(go())


def test_a_change_that_happens_while_the_lease_moves_wakes_once(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as site_a:
            await site_a.arm("working", 1001)
            site_a.bridge.state("working", 1001)
            assert (await site_a.tick())["woke"] == 0
        # the lease is lost and the session finishes, with two more state changes than the check ever saw
        async with watching(db_url, site_a) as site_b:
            site_b.bridge.state("done", 1004)
            assert (await site_b.tick())["woke"] == 1 and (await site_b.tick())["woke"] == 0
            assert [s for _, s in told(db_url)] == ["done"]
    run(go())


def test_two_holders_that_checked_the_same_finish_store_one_wake(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.state("done", 1002)
            await w.due_now()
            [due] = await services.get(Watches).due(10)
            read = {due.id: session("done", 1002, due.target)}
            [first, second] = [judge(read[due.id], due)] * 2
            store = services.get(Watches)
            assert await store.record(due.id, due.version, first) and not await store.record(due.id, due.version, second)
            assert len(told(db_url)) == 1
    run(go())


def test_a_holder_that_dies_after_the_wake_is_stored_leaves_the_same_turn_for_the_next(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as site_a:
            await site_a.arm("working", 1001)
            site_a.bridge.state("done", 1002)
            assert (await site_a.tick())["woke"] == 1   # stored with the baseline; the turn never ran
        async with watching(db_url, site_a) as site_b:
            site_b.bridge.state("done", 1002)
            assert (await site_b.tick())["due"] == 0   # not checked again while its wake waits
            [due] = await services.get(Wakes).due(10)
            assert isinstance(due.wake, WatchWake) and due.wake.what == "changed"
            watch_ = await services.get(Watches).get(due.wake.watch_id)
            assert watch_ is not None
            turn = watch_turn.inbound(due.id, watch_, due.wake, False)
            assert turn.source == f"wake:{due.id}" and len(told(db_url)) == 1
    run(go())


def test_a_bridge_that_cannot_be_reached_changes_nothing_and_the_finish_is_found_when_it_can(
        db_url: str, connection_kinds_wired: None, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.state("done", 1002)
            w.bridge.down = True
            for _ in range(CONFIG.fail_after - 1):
                assert (await w.tick())["failed"] == 1
            assert states(db_url) == [("working", 1001)] and told(db_url) == []
            w.bridge.down = False
            assert (await w.tick())["woke"] == 1 and states(db_url) == [("done", 1002)]
    run(go())
    seen = capsys.readouterr()
    lost = events(seen.out + seen.err, "watches.read_failed")
    assert {e["reason"] for e in lost} == {"unreachable"} and {e["kind"] for e in lost} == {"claude_session"}


def test_a_person_who_has_removed_their_bridge_is_not_asked(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.connections.held.clear()
            w.bridge.state("done", 1002)
            counts = await w.tick()
            assert counts["failed"] == 1 and counts["woke"] == 0 and w.bridge.asked == 0
            assert states(db_url) == [("working", 1001)]
    run(go())


def test_a_session_gone_from_its_bridge_ends_its_watch_and_the_ended_watch_is_forgotten_after_the_keeping(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001, target="gone")
            counts = await w.tick()
            assert counts["woke"] == 0 and counts["ended"] == 1 and counts["baselines"] + counts["quiet"] == 1
            assert scalar(db_url, "SELECT count(*) FROM watches WHERE state = 'ended' AND reason = 'until'") == 1
            scalar(db_url, "WITH u AS (UPDATE watches SET ended_at = now() - make_interval(secs => %s) "
                           "RETURNING 1) SELECT count(*) FROM u", (CONFIG.keep_s + 5,))
            await w.tick()
            assert scalar(db_url, "SELECT count(*) FROM watches") == 0
    run(go())


def test_the_tick_logs_ids_and_counts_and_never_a_label_or_directory(
        db_url: str, connection_kinds_wired: None, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.state("done", 1002)
            await w.tick()
    run(go())
    out = capsys.readouterr()
    text = out.out + out.err
    [woke] = events(text, "watches.woke")
    assert woke["series"] == "1" and woke["changed"] == "1" and woke["watch"].isdigit()
    [ticked] = events(text, "watches.tick")
    assert (ticked["due"], ticked["woke"]) == ("1", "1")
    assert "bridge-capture" not in text and "scratch" not in text and "s-" not in woke["watch"]


def test_run_checks_every_interval_until_cancelled(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.state("done", 1002)
            await w.due_now()
            waits: list[float] = []

            async def sleep(seconds: float) -> None:
                waits.append(seconds)
                if len(waits) == 3:
                    raise asyncio.CancelledError

            with pytest.raises(asyncio.CancelledError):
                await job.run(CONFIG, job.KINDS, sleep)
            assert waits == [CONFIG.tick_s] * 3 and len(told(db_url)) == 1
    run(go())


def test_a_handoff_watch_lasts_the_kinds_handoff_hours(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            hours = scalar(db_url, "SELECT extract(epoch FROM expires_at - armed_at) / 3600 FROM watches")
            assert abs(float(hours) - KIND.handoff_hours) < 0.1
    run(go())

