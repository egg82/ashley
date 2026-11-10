"""What a tainted turn writes carries the taint (design 2.1): a reminder and a watch made in one fire `inherited`, a bench
piece it adds or edits is `outside` for good, and a list it wrote reads back as outside for a while. Over a real database
where the store is the point."""

import json
from dataclasses import replace
from typing import NoReturn
from datetime import UTC, datetime, timedelta

from ashley.channels.wake import reminder_turn, watch_turn
from ashley.people.model import Person
from ashley.senses.wakes import Reminder, WatchWake
from ashley.db.pool import PoolDatabase
from ashley.watches.config import CONFIG
from ashley.watches.model import Arm
from ashley.watches.postgres import PostgresWatches
from ashley.workshop.codec import decode_effect, encode_effect
from ashley.workshop.commands import Add, Edit, Undo
from ashley.workshop.decide import Accepted, replay
from ashley.workshop.model import HER, By, Text
from ashley.workshop.rules import Kind, Rules
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run
from test_reminders_postgres import MONTHLY, reminder, store
from watch_job_support import watch as a_watch

NOTE = Kind("note", "stored", "Note", 10)
RULES = Rules({"note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
OUTSIDE = By(None, outside=True)


def test_a_reminder_made_in_a_tainted_turn_keeps_its_taint_through_the_store_and_each_repeat(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as wakes:
            await wakes.schedule(replace(reminder(home, alana, repeat=MONTHLY), taint="mail_read"))
            await wakes.schedule(reminder(home, alana, brief="the household's own"))
            due = {d.wake.brief: (d.id, d.wake.taint) for d in await wakes.due(10) if isinstance(d.wake, Reminder)}
            repeating_id, repeating_taint = due["Move anything over $300 in Bluebird checking to savings."]
            assert repeating_taint == "mail_read" and due["the household's own"][1] is None
            assert await wakes.settle(repeating_id, "turn", datetime.now(UTC) + timedelta(days=30))
            listed = [s.reminder for s in await wakes.reminders(home, alana)]
            assert sorted((r.brief[:4], r.taint) for r in listed if r.due_at > datetime.now(UTC)) == [("Move", "mail_read")]

    run(go())


def test_changing_a_reminder_never_clears_its_taint_and_a_tainted_change_sets_it(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as wakes:
            tainted = await wakes.schedule(replace(reminder(home, alana, in_s=3600), taint="look_up"))
            plain = await wakes.schedule(reminder(home, alana, in_s=3600))
            assert await wakes.edit(home, alana, tainted, reminder(home, alana, in_s=7200, brief="by the person"))
            assert await wakes.edit(home, alana, plain, replace(reminder(home, alana, in_s=7200, brief="edited"), taint="look_up"))
            got = {s.id: s.reminder.taint for s in await wakes.reminders(home, alana)}
            assert got == {tainted: "look_up", plain: "look_up"}

    run(go())


def test_the_turn_a_tainted_reminder_fires_starts_inherited_and_another_starts_untainted() -> None:
    alana = Person(7, 1, "Alana")
    due = datetime(2026, 11, 8, tzinfo=UTC)
    plain = Reminder(1, 7, 7, "water the plants", due, None)
    assert reminder_turn.inbound(5, plain, alana, alana).taint is None
    assert reminder_turn.inbound(5, replace(plain, taint="mail_read"), alana, alana).taint == "inherited"


def test_a_tainted_watch_s_wake_is_inherited_unless_its_kind_is_outside_already() -> None:
    wake = WatchWake(1, 7, 1, "paused", {"reason": "unreadable"})
    session = a_watch()
    assert watch_turn.inbound(3, session, wake, on_bench=False).taint is None
    assert watch_turn.inbound(3, replace(session, taint="look_up"), wake, on_bench=False).taint == "inherited"
    unknown = a_watch(kind="no_such_kind")
    assert watch_turn.inbound(3, replace(unknown, taint="look_up"), wake, on_bench=False).taint == "watch"


def arm_of(household_id: int, person_id: int, target: str = "a@example.test", **over: object) -> Arm:
    kind = CONFIG.kinds["mail_inbox"]
    return replace(Arm(household_id, person_id, "mail_inbox", target, "inbox", None, "ashley", kind.track, kind.when, None,
                       ("mail_label",), kind.interval_s, datetime.now(UTC) + timedelta(hours=6)), **over)


def test_a_watch_armed_in_a_tainted_turn_keeps_its_taint_and_arming_again_never_clears_it(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            watches = PostgresWatches(database, CONFIG)
            first = await watches.arm(arm_of(home, alana, taint="mail_read"))
            assert (await watches.get(first.id) or fail()).taint == "mail_read"
            again = await watches.arm(arm_of(home, alana))
            assert again.id == first.id and not again.new
            assert (await watches.get(first.id) or fail()).taint == "mail_read"
            other = await watches.arm(arm_of(home, alana, "b@example.test"))
            assert (await watches.get(other.id) or fail()).taint is None
        finally:
            await database.close()

    run(go())


def fail() -> NoReturn:
    raise AssertionError("no such watch")


def test_a_piece_added_or_edited_by_a_tainted_turn_is_outside_and_stays_so() -> None:
    plain = Add(By(7), "note", Text("a", ""), "small")
    outside = Add(OUTSIDE, "note", Text("b", ""), "small")
    done = replay([plain, outside, Edit(By(7), 2, 1, Text("c", "mine")), Edit(OUTSIDE, 1, 1, Text("d", "theirs")),
                   Undo(By(7), 4)], RULES)
    assert all(isinstance(d, Accepted) for d in done)
    assert [(p.id, p.outside) for p in done[1].state.pieces] == [(1, False), (2, True)]
    assert [(p.id, p.outside) for p in done[2].state.pieces] == [(1, False), (2, True)], "a person's edit does not clear it"
    assert [(p.id, p.outside) for p in done[3].state.pieces] == [(1, True), (2, True)]
    assert [(p.id, p.outside) for p in done[4].state.pieces] == [(1, True), (2, True)], "an undo does not clear it"


def test_the_outside_flag_is_stored_with_a_piece_and_with_its_effect_and_a_plain_piece_stores_no_flag() -> None:
    done = replay([Add(OUTSIDE, "note", Text("b", ""), "small"), Add(HER, "note", Text("c", ""), "small")], RULES)
    effects = [d.effect for d in done if isinstance(d, Accepted)]
    first, second = (encode_effect(e) for e in effects)
    assert '"outside": true' in json.dumps(first) and "outside" not in json.dumps(second)
    assert decode_effect(first) == effects[0] and decode_effect(second) == effects[1]


def test_a_piece_the_tainted_turn_added_is_outside_when_read_back_from_the_database(db_url: str) -> None:
    from test_workshop_postgres import people, workshop_on

    alana, _, _ = people(db_url)

    async def go() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, "desk")
            await shop.apply(alana, bench.id, Add(By(None, outside=True), "note", Text("a", "x"), "small"))
            await shop.apply(alana, bench.id, Add(HER, "note", Text("b", "y"), "small"))
            view = await shop.read(alana, bench.id)
            assert [(p.text.title, p.outside) for p in view.pieces] == [("a", True), ("b", False)]

    run(go())
