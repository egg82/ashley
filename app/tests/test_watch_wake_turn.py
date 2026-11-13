"""The turn a watch's wake starts, for the session sense, over a real database and the real turn loop: it runs on the
bench's talk that handed the session work, or on the person's phone thread when that bench is closed; it is one turn
however often it is handed in; a hand-off watch has the thread's tools, any other the ones that read or those it names. She is told, per call, whether the person has a page
open on either site and that a push reaches their phone, and a push goes only when she sets `to_phone` and the phone
can be reached: never by code on its own."""

from dataclasses import replace

import pytest
from ashley import logs, services
from ashley.channels import respond as respond_module
from ashley.channels import unprompted
from ashley.channels.audience import owner_alone
from ashley.inference.model import ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.channels.wake import watch_turn
from ashley.criteria.record import Change
from ashley.herdr.model import Status
from ashley.senses.wakes import Due, Wakes, WatchWake
from ashley.watches import claude_session
from ashley.watches.config import CONFIG as WATCHES
from ashley.watches.registry import KINDS
from ashley.watches.rows import changed_wake
from ashley.live.live import load as live_config
from ashley.live.postgres_screens import PostgresScreens
from ashley.live.screens import Screens
from ashley.db.pool import PoolDatabase
from bench_reacts_support import SAYS, has_aside, last_message
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import events, run, scalar
from watch_job_support import NOW, watch as a_watch
from watch_session_support import SESSION, Watching, watching


async def woken(w: Watching, bench: int | None, status: Status = "done", seq: int = 1002) -> Due:
    """The wake the session moving to `status` at `seq` stores, for the watch a hand-off from `bench` armed."""
    await w.arm("working", 1001, bench)
    await w.settle()
    w.bridge.state(status, seq)
    await w.tick()
    [due] = await services.get(Wakes).due(10)
    return due


async def tell(w: Watching, bench: int | None, status: Status = "done", seq: int = 1002) -> bool:
    """Run her turn on that wake; whether it ran."""
    due = await woken(w, bench, status, seq)
    assert isinstance(due.wake, WatchWake)
    return await watch_turn.fired(due.id, due.wake, due.age_s) == "turn"


def turns_on(url: str, thread: str) -> list[tuple[str, str, str | None]]:
    got = scalar(url, "SELECT coalesce(json_agg(json_build_array(t.author, t.text, t.source) ORDER BY t.id), '[]') "
                      "FROM turns t JOIN conversations c ON c.id = t.conversation_id WHERE c.thread = %s", (thread,))
    return [(a, t, s) for a, t, s in got]


def pushes(url: str) -> list[tuple[str, str]]:
    got = scalar(url, "SELECT coalesce(json_agg(json_build_array(thread, body) ORDER BY id), '[]') FROM outbox "
                      "WHERE starts_with(thread, 'push:')")
    return [(t, b) for t, b in got]


def test_the_wake_runs_on_the_bench_that_handed_the_session_work_from_its_fields_with_a_note_for_her(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.home.model.script = [SAYS]
            due = await woken(w, bench)
            due_id = due.id
            assert isinstance(due.wake, WatchWake) and await watch_turn.fired(due.id, due.wake, due.age_s) == "turn"
            [(author, text, source), hers] = turns_on(db_url, f"bench:{bench}")
            assert (author, text, source) == ("household", "Claude Code session bridge-capture: done",
                                              f"wake:{due_id}")
            assert hers == ("ashley", SAYS.text, None)
            assert claude_session.DONE_NOTE in last_message(w.home.model.prompts[0])
    run(go())


def test_a_blocked_session_tells_her_she_cannot_answer_it(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.home.model.script = [SAYS]
            await tell(w, bench, "blocked", 1003)
            assert claude_session.BLOCKED_NOTE in last_message(w.home.model.prompts[0])
            assert turns_on(db_url, f"bench:{bench}")[0][1].endswith(": blocked")
    run(go())


@pytest.mark.parametrize("status,expected", [("done", claude_session.DONE_NOTE), ("idle", claude_session.DONE_NOTE),
                                             ("blocked", claude_session.BLOCKED_NOTE)])
def test_a_finish_someone_has_looked_at_is_still_a_finish_to_her(status: Status, expected: str) -> None:
    change = Change(SESSION, "changed", {"status": "working", "seq": 1001}, {"status": status, "seq": 1002})
    assert KINDS.get("claude_session").note(a_watch(), [change]) == expected
    assert KINDS.get("claude_session").said(a_watch(), [change]) == f"Claude Code session label: {status}"


def test_a_session_that_closed_is_told_as_closed() -> None:
    change = Change(SESSION, "gone", {"status": "done", "seq": 1001}, None)
    assert KINDS.get("claude_session").note(a_watch(), [change]) == claude_session.CLOSED_NOTE
    assert KINDS.get("claude_session").said(a_watch(), [change]) == "Claude Code session label: closed"


def test_the_same_wake_handed_in_twice_is_one_turn(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.home.model.script = [SAYS, SAYS]
            due = await woken(w, bench)
            assert isinstance(due.wake, WatchWake)
            for _ in range(2):   # a runner killed mid-turn hands the same wake in again
                assert await watch_turn.fired(due.id, due.wake, due.age_s) == "turn"
            assert [a for a, _, _ in turns_on(db_url, f"bench:{bench}")] == ["household", "ashley"]
    run(go())


def facts_of(w: Watching) -> str:
    """The facts of the moment the woken turn's prompt carried."""
    return w.home.model.prompts[0].system["default"].moment


WITH_PUSH = Reply(spoken="Done.", text="The session finished.", says="reply", to_phone=True)


def test_a_closed_bench_or_none_sends_the_wake_to_the_phone_thread_whose_reply_is_the_push(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            await w.home.workshop.close(w.home.owner, bench)
            w.home.model.script = [SAYS, SAYS]
            w.subscribe()
            assert await tell(w, bench) and await tell(w, None, seq=1003)
            assert turns_on(db_url, f"bench:{bench}") == []
            assert len(turns_on(db_url, f"push:{w.person}")) == 4
            assert pushes(db_url) == [(f"push:{w.person}", SAYS.text)] * 2   # the thread's own push, never doubled
            assert "to_phone" not in facts_of(w) and "page open" not in facts_of(w)   # nothing to choose there
    run(go())


def test_she_is_told_no_page_is_open_and_a_push_reaches_the_phone_and_her_field_sends_it(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.subscribe()
            w.home.model.script = [WITH_PUSH]
            assert await tell(w, bench)
            assert "has no page open on any device" in facts_of(w) and "set `to_phone`" in facts_of(w)
            assert pushes(db_url) == [(f"push:{w.person}", WITH_PUSH.text)]
            assert len(turns_on(db_url, f"bench:{bench}")) == 2   # and her reply is on the bench's talk as well
    run(go())


def test_nothing_is_pushed_unless_she_sets_the_field(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.subscribe()
            w.home.model.script = [SAYS]
            assert await tell(w, bench)
            assert "has no page open" in facts_of(w) and pushes(db_url) == []
    run(go())


def test_a_page_open_on_the_other_site_is_a_fact_she_is_given_and_the_closed_page_is_too(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            other_site = PoolDatabase(db_url, connect_timeout_s=5.0)
            await other_site.open()
            try:
                bench = await w.home.bench()
                w.subscribe()
                shown = await PostgresScreens(other_site).opened(w.home.home, w.person)   # a stream held by a pod elsewhere
                w.home.model.script = [SAYS]
                assert await tell(w, bench)
                assert "has a page open" in facts_of(w) and "no page open" not in facts_of(w)
                await PostgresScreens(other_site).closed(shown)
                w.home.model.script = [SAYS]
                w.home.model.prompts.clear()
                assert await tell(w, bench, seq=1003)
                assert "has no page open on any device" in facts_of(w)
            finally:
                await other_site.close()
    run(go())


def test_a_screen_whose_pod_died_is_no_longer_a_page_open(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.subscribe()
            await services.get(Screens).opened(w.home.home, w.person)
            scalar(db_url, "WITH u AS (UPDATE live_screens SET seen_at = now() - make_interval(secs => %s) "
                           "RETURNING 1) SELECT count(*) FROM u", (live_config().present_s + 5,))
            w.home.model.script = [SAYS]
            assert await tell(w, bench)
            assert "has no page open on any device" in facts_of(w)
    run(go())


def test_with_no_browser_she_is_not_offered_the_phone_and_her_field_is_ignored(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.home.model.script = [WITH_PUSH]
            assert await tell(w, bench)
            assert "to_phone" not in facts_of(w) and "page open" not in facts_of(w)
            assert pushes(db_url) == [] and len(turns_on(db_url, f"bench:{bench}")) == 2
    run(go())


def test_screens_that_cannot_be_read_leave_the_page_fact_out_but_the_phone_still_offered(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            services.unregister(Screens)   # the Null Object raises, as an unreachable record would
            bench = await w.home.bench()
            w.subscribe()
            w.home.model.script = [WITH_PUSH]
            assert await tell(w, bench)
            assert "page open" not in facts_of(w) and "set `to_phone`" in facts_of(w)
            assert pushes(db_url) == [(f"push:{w.person}", WITH_PUSH.text)]
    run(go())


def test_a_silent_wake_posts_nothing_to_any_thread_and_pushes_nothing_and_says_so_in_the_log(
        db_url: str, connection_kinds_wired: None, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.subscribe()
            w.home.model.script = [WITH_PUSH.model_copy(update={"says": "none"})]   # the push field is set too
            assert await tell(w, bench)
            assert pushes(db_url) == []
            assert [t for a, t, _ in turns_on(db_url, f"bench:{bench}") if a == "ashley"] == [unprompted.QUIET]
    run(go())
    [outcome] = events(capsys.readouterr().out, "wake.outcome")
    assert outcome["outcome"] == "silent"


def test_the_outcome_is_logged_as_thread_or_phone_by_what_she_chose(
        db_url: str, connection_kinds_wired: None, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.subscribe()
            w.home.model.script = [SAYS, WITH_PUSH]
            await tell(w, bench)
            await tell(w, bench, seq=1003)
    run(go())
    assert [e["outcome"] for e in events(capsys.readouterr().out, "wake.outcome")] == ["thread", "phone"]


def wake_of(status: Status, series: int = 1, ended: bool = False) -> WatchWake:
    before, after = {"status": "working", "seq": 1001}, {"status": status, "seq": 1002}
    return WatchWake(1, 7, 1, "changed", changed_wake(series, NOW, ended, (Change(SESSION, "changed", before, after),)))


def test_the_woken_turn_reaches_the_person_alone_and_a_hand_off_keeps_the_threads_tools() -> None:
    watch_ = replace(a_watch(person=7), bench_id=5, armed_by="handoff")
    for on_bench in (True, False):
        made = watch_turn.inbound(9, watch_, wake_of("done"), on_bench)
        assert made.unprompted and not made.promised and not made.reads_only and made.tools_only is None
        assert made.audience == "owner" and owner_alone(made) and made.author == "household" and made.source == "wake:9"
    assert watch_turn.inbound(9, watch_, wake_of("done"), True).thread == "bench:5"
    assert watch_turn.inbound(9, watch_, wake_of("done"), False).thread == "push:7"
    assert watch_turn.inbound(9, replace(watch_, bench_id=None), wake_of("done"), True).thread == "push:7"


def test_a_watch_she_armed_offers_what_changes_nothing_unless_it_names_tools() -> None:
    watch_ = replace(a_watch(person=7), armed_by="ashley")
    plain = watch_turn.inbound(9, watch_, wake_of("done"), False)
    assert plain.reads_only and plain.tools_only is None
    named = watch_turn.inbound(9, replace(watch_, tools=("claude_read",)), wake_of("done"), False)
    assert not named.reads_only and named.tools_only == ("claude_read",)


def test_the_note_carries_the_series_since_and_whether_the_watch_ended() -> None:
    watch_ = a_watch(person=7)
    first = watch_turn.note(watch_, wake_of("done", series=3, ended=True))
    assert "wake 3 of this watch" in first and NOW.isoformat() in first and "has now ended" in first
    assert "has now ended" not in watch_turn.note(watch_, wake_of("done"))


def test_a_paused_watch_is_told_as_paused_with_its_reason() -> None:
    paused = WatchWake(1, 7, 1, "paused", {"what": "paused", "reason": "unreachable"})
    assert watch_turn.said(a_watch(), paused) == "Watch label: paused, unreachable"
    assert watch_turn.note(a_watch(), paused) == watch_turn.PAUSED_NOTE


def test_a_wake_older_than_the_keeping_expires_and_a_wake_of_no_watch_is_cancelled(
        db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            due = await woken(w, None)
            assert isinstance(due.wake, WatchWake)
            late = WATCHES.wake_max_age_s + 1
            assert await watch_turn.fired(due.id, due.wake, late) == "expired"
            gone = replace(due.wake, watch_id=due.wake.watch_id + 1000)
            assert await watch_turn.fired(due.id, gone, 0.0) == "cancelled"
            assert turns_on(db_url, f"push:{w.person}") == []
    run(go())


def test_a_watch_wake_is_offered_no_aside_and_holds_nothing(
        db_url: str, connection_kinds_wired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    limits = respond_module.LIMITS
    monkeypatch.setitem(limits, "brainstorm", replace(limits["brainstorm"], hold_after_s=0.0))

    async def go() -> None:
        async with watching(db_url) as w:
            bench = await w.home.bench()
            w.home.model.script = [ToolCalls((ToolCall("c1", "look", {}),)), SAYS]
            assert await tell(w, bench) is True
            assert not any(has_aside(t) for t in w.home.model.prompts[0].tools)
            assert [t for a, t, _ in turns_on(db_url, f"bench:{bench}") if a == "ashley"] == [SAYS.text]
    run(go())


def test_a_wake_whose_changes_cannot_be_read_fails_without_a_turn(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            due = await woken(w, None)
            assert isinstance(due.wake, WatchWake)
            broken = replace(due.wake, changes={"what": "changed", "items": [{"id": "s", "kind": "sideways"}]})
            assert await watch_turn.fired(due.id, broken, 0.0) == "failed"
            assert turns_on(db_url, f"push:{w.person}") == []
    run(go())
