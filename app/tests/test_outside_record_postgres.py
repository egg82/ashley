"""The outside record over a real database: what a turn did on its own reads back by turn, past-limit rows go when the next
is written and in-limit ones stay, a list a tainted turn wrote counts as outside only within its window, and one household's
notes are never another's."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from ashley.db.pool import PoolDatabase
from ashley.senses.outside_record import DoneAction
from ashley.senses.postgres_outside_record import PostgresOutsideRecord
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar

DAY = 86400.0


@asynccontextmanager
async def record(url: str, actions_keep_s: float = 90 * DAY, writes_keep_s: float = 7 * DAY) -> AsyncGenerator[PostgresOutsideRecord]:
    database = PoolDatabase(url, connect_timeout_s=5.0)
    await database.open()
    try:
        yield PostgresOutsideRecord(database, actions_keep_s, writes_keep_s)
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
