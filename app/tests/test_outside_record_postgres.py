"""The outside record over a real database: what a turn did on its own reads back by turn, past-limit rows go when the next
is written and in-limit ones stay, a list a tainted turn wrote counts as outside only within its window, and one household's
notes are never another's. A change's cause and undo read back with it, and a row kept before them, or naming a kind this
release does not know, reads back with neither."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from ashley.db.pool import PoolDatabase
from ashley.senses.outside_record import Cause, DoneAction
from ashley.senses.postgres_outside_record import PostgresOutsideRecord
from ashley.undo import Undo
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar


def execute(url: str, query: str, params: tuple[object, ...]) -> None:
    with psycopg.connect(url) as conn:
        conn.execute(query.encode(), params)


DAY = 86400.0


@asynccontextmanager
async def record(url: str, actions_keep_s: float = 90 * DAY, writes_keep_s: float = 7 * DAY,
                 quiet_keep_s: float = 7 * DAY) -> AsyncGenerator[PostgresOutsideRecord]:
    database = PoolDatabase(url, connect_timeout_s=5.0)
    await database.open()
    try:
        yield PostgresOutsideRecord(database, actions_keep_s, writes_keep_s, quiet_keep_s)
    finally:
        await database.close()


def action(home: int, who: int, turn: int = 1, tool: str = "mail_label", days_ago: float = 0.0, tier: str = "runs",
           reason: str | None = None, explanation: str | None = None) -> DoneAction:
    return DoneAction(home, who, 40, turn, tool, f"{tool} (x)", tier, reason, explanation,
                      datetime.now(UTC) - timedelta(days=days_ago), f"Did {tool}")


def test_what_a_turn_did_reads_back_by_turn_oldest_first_with_why_when_the_judge_ran_it(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with record(db_url) as rec:
            await rec.done(action(home, alana, 1, "mail_label"))
            await rec.done(action(home, alana, 1, "mail_send", tier="judged", reason="asked_directly",
                                  explanation="You asked."))
            await rec.done(action(home, alana, 2, "light"))
            got = await rec.of_turn(40, 1)
            assert [(a.tool, a.tier, a.reason, a.explanation) for a in got] == [
                ("mail_label", "runs", None, None), ("mail_send", "judged", "asked_directly", "You asked.")]
            assert [a.label for a in got] == ["Did mail_label", "Did mail_send"], "the headline it was shown under is kept"
            assert [a.tool for a in await rec.of_turn(40, 2)] == ["light"] and await rec.of_turn(40, 3) == ()

    run(go())


def test_an_action_past_the_limit_is_pruned_when_the_next_is_written_and_one_within_it_stays(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with record(db_url) as rec:
            await rec.done(action(home, alana, 1, "old", days_ago=91))
            assert [a.tool for a in await rec.of_turn(40, 1)] == ["old"], "nothing prunes until the next write: control"
            await rec.done(action(home, alana, 2, "almost", days_ago=89))
            assert await rec.of_turn(40, 1) == ()
            assert [a.tool for a in await rec.of_turn(40, 2)] == ["almost"]
            await rec.done(action(home, alana, 3, "new"))
            assert [a.tool for a in await rec.of_turn(40, 2)] == ["almost"] and [a.tool for a in await rec.of_turn(40, 3)] == ["new"]

    run(go())
    assert int(scalar(db_url, "SELECT count(*) FROM outside_actions")) == 2


def test_a_list_written_by_a_tainted_turn_is_outside_within_its_window_only_and_its_row_is_pruned(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "next door")

    async def go() -> None:
        async with record(db_url) as rec:
            now = datetime.now(UTC)
            await rec.wrote(home, "todo.stale", now - timedelta(days=8))
            assert not await rec.written(home, ["todo.stale"])
            await rec.wrote(home, "todo.fresh", now - timedelta(days=1))
            assert int(scalar(db_url, "SELECT count(*) FROM outside_writes WHERE entity = 'todo.stale'")) == 0, "pruned"
            assert await rec.written(home, ["todo.inbox", "todo.fresh"]) and not await rec.written(home, ["todo.inbox"])
            assert not await rec.written(other, ["todo.fresh"]) and not await rec.written(home, [])
            await rec.wrote(home, "todo.fresh", now)
            assert int(scalar(db_url, "SELECT count(*) FROM outside_writes WHERE entity = 'todo.fresh'")) == 1, "one row"

    run(go())


def test_a_person_reads_back_only_their_own_newest_first_up_to_the_limit(db_url: str) -> None:
    home, other = household(db_url), household(db_url)
    alana, sam, kim = person(db_url, home, "Alana"), person(db_url, home, "Sam"), person(db_url, other, "Kim")

    async def go() -> None:
        async with record(db_url) as rec:
            await rec.done(action(home, alana, 1, "old", days_ago=2))
            await rec.done(action(home, alana, 2, "new", days_ago=1))
            await rec.done(action(home, sam, 3, "sams"))
            await rec.done(action(other, kim, 4, "kims"))
            await rec.done(action(other, alana, 5, "same id elsewhere"))
            got = await rec.of_person(home, alana, 10)
            assert [r.action.tool for r in got] == ["new", "old"] and got[0].id > got[1].id
            assert [r.action.tool for r in await rec.of_person(home, alana, 1)] == ["new"]
            assert await rec.of_person(home, kim, 10) == ()

    run(go())


def test_a_cause_and_an_undo_read_back_by_turn_and_by_person_and_an_older_row_reads_with_neither(db_url: str) -> None:
    home, other = household(db_url), household(db_url)
    alana, sam, kim = person(db_url, home, "Alana"), person(db_url, home, "Sam"), person(db_url, other, "Kim")
    woke = replace(action(home, alana, 1, "remind"), cause=Cause("standing_errand", 55),
                   undo=Undo("todo_remove", "Lemons", "todo.grocery"))

    async def go() -> None:
        async with record(db_url) as rec:
            await rec.done(woke)
            await rec.done(replace(action(home, sam, 2, "light"), cause=Cause("watch", 9)))
            await rec.done(replace(action(other, kim, 3, "light"), cause=Cause("wake", 4)))
            [got] = await rec.of_turn(40, 1)
            assert (got.cause, got.undo) == (woke.cause, woke.undo)
            assert [(r.action.cause, r.action.undo) for r in await rec.of_person(home, alana, 10)] == [(woke.cause, woke.undo)]
            assert [r.action.cause for r in await rec.of_person(home, sam, 10)] == [Cause("watch", 9)]
            assert await rec.of_person(other, alana, 10) == ()

    run(go())
    execute(db_url, "INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, tier, "
                    "decision, at) VALUES (%s, %s, 40, 7, 'old', 'old (x)', 'runs', 'run', now())", (home, alana))
    execute(db_url, "UPDATE outside_actions SET cause_kind = 'rumour', undo_kind = 'unsend', undo_ref = '1' WHERE tool = 'light' "
                    "AND household_id = %s", (home,))

    async def older() -> None:
        async with record(db_url) as rec:
            [old] = await rec.of_turn(40, 7)
            assert (old.tool, old.cause, old.undo) == ("old", None, None)
            [unknown] = await rec.of_person(home, sam, 10)
            assert (unknown.action.cause, unknown.action.undo) == (None, None), "a kind this release does not know"

    run(older())


def test_a_change_made_on_her_own_is_pruned_past_the_limit_like_any_other(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")
    woke = Cause("wake", 4)

    async def go() -> None:
        async with record(db_url) as rec:
            await rec.done(replace(action(home, alana, 1, "old", days_ago=91), cause=woke, undo=Undo("reminder_cancel", "8")))
            await rec.done(replace(action(home, alana, 2, "new"), cause=woke))
            assert [r.action.tool for r in await rec.of_person(home, alana, 10)] == ["new"]

    run(go())


@pytest.mark.parametrize("column, value", [("cause_kind", "wake"), ("cause_id", 3), ("undo_kind", "reminder_cancel"),
                                           ("undo_ref", "4")])
def test_half_a_cause_or_half_an_undo_is_refused_by_the_table(db_url: str, column: str, value: object) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")
    insert = ("INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, tier, "
              "decision, at, {}) VALUES (%s, %s, 1, 1, 't', 's', 'runs', 'run', now(), %s)")
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(db_url, insert.format(column), (home, alana, value))


def test_an_undo_is_claimed_once_settled_or_given_up_and_a_lapsed_claim_can_be_taken_again(db_url: str) -> None:
    home, other = household(db_url), household(db_url)
    alana, sam = person(db_url, home, "Alana"), person(db_url, home, "Sam")

    async def go() -> None:
        async with record(db_url) as rec:
            await rec.done(replace(action(home, alana, 1, "remind"), undo=Undo("reminder_cancel", "4")))
            await rec.done(action(home, alana, 2, "mail_send"))
            bare, first = (r.id for r in await rec.of_person(home, alana, 10))
            assert await rec.one(home, sam, first) is None and await rec.one(other, alana, first) is None
            assert not await rec.claim_undo(home, sam, first, 60) and not await rec.claim_undo(other, alana, first, 60)
            assert not await rec.claim_undo(home, alana, bare, 60), "an action with no undo has none to take"
            assert await rec.claim_undo(home, alana, first, 60)
            assert not await rec.claim_undo(home, alana, first, 60), "a live claim is not taken twice"
            claimed = await rec.one(home, alana, first)
            assert claimed is not None and claimed.undone is not None and (claimed.undone.how, claimed.undone.by) == ("undoing", alana)
            await rec.settle_undo(first, None)
            given_up = await rec.one(home, alana, first)
            assert given_up is not None and given_up.undone is None
            assert await rec.claim_undo(home, alana, first, 60)
            execute(db_url, "UPDATE outside_actions SET undone_at = now() - interval '1 hour' WHERE id = %s", (first,))
            assert await rec.claim_undo(home, alana, first, 60), "a claim left by a stopped pod lapses"
            await rec.settle_undo(first, "gone")
            assert not await rec.claim_undo(home, alana, first, 0.001), "a settled undo is never taken again"
            await rec.settle_undo(first, None)
            settled = (await rec.of_person(home, alana, 10))[1]
            assert settled.undone is not None and settled.undone.how == "gone", "giving up leaves a settled undo as it is"

    run(go())


@pytest.mark.parametrize("columns, values", [
    ("undo_kind, undo_ref, undone_at, undone_by", "'reminder_cancel', '4', now(), 1"),
    ("undo_kind, undo_ref, undone_at, undone_how", "'reminder_cancel', '4', now(), 'undone'"),
    ("undone_at, undone_by, undone_how", "now(), 1, 'undone'"),
    ("undo_kind, undo_ref, undone_at, undone_by, undone_how", "'reminder_cancel', '4', now(), 1, 'redone'")])
def test_an_undone_mark_must_be_whole_known_and_on_a_row_with_an_undo(db_url: str, columns: str, values: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")
    insert = ("INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, tier, "
              f"decision, at, {columns}) VALUES (%s, %s, 1, 1, 't', 's', 'runs', 'run', now(), {values})")
    with pytest.raises(psycopg.errors.CheckViolation):
        execute(db_url, insert, (home, alana))
