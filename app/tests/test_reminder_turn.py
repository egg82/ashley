"""A reminder firing, over a real database: the `wakes` singleton's sweep takes a reminder once its time has come and
runs her turn on it through the shared turn loop, with only tools that read, on the phone thread of the person it is for, and what
she says is stored to go out whatever `worth_saying` says, since the person asked for it (its push:
test_reminder_delivery). A one-off fires once; a repeating one
fires each occurrence once, across two runners at once and a runner killed mid-turn, its next occurrence in the
household's wall-clock time; occurrences missed in an outage fire once; a cancelled one never fires again; and no log
line carries what the reminder says."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from ashley import logs, services
from ashley.channels import resume
from ashley.channels.audience import owner_alone
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.wake import reminder_turn, runner
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference, InferenceRefused
from ashley.inference.model import Message
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.presence import Presence
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder, Wakes
from ashley.tools.tools import Tools
from contract.conversations_support import POLICY, db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import events, person, run, scalar
from wake_support import Model, Nobody, Switchboard

DENVER = ZoneInfo("America/Denver")
BRIEF = "Pay off the NGFCU Visa now that pay landed: $1,234.56. Then switch Proton to it."
SAYS = Reply(spoken="Your reminder.", text="Pay day: time to clear the Visa.", worth_saying=False)


@dataclass
class Home(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class World:
    url: str
    home: int
    alana: int
    sam: int
    model: Model
    wakes: Wakes

    async def remind(self, for_id: int | None = None, by: int | None = None, *, due_at: datetime | None = None,
                     repeat: Repeat | None = None) -> int:
        who = for_id or self.alana
        return await self.wakes.schedule(Reminder(self.home, who, by or who, BRIEF,
                                                  due_at or datetime.now(UTC) - timedelta(seconds=1), repeat))

    def queued(self) -> list[tuple[str, str]]:
        got = scalar(self.url, "SELECT coalesce(json_agg(json_build_array(thread, body) ORDER BY id), '[]') "
                               "FROM outbox")
        return [(t, b) for t, b in got]

    def answers(self) -> list[tuple[str, str]]:
        """Her stored answers, each with the thread its conversation is on: what a fired reminder says, and where."""
        got = scalar(self.url, "SELECT coalesce(json_agg(json_build_array(ct.thread, t.text) ORDER BY t.id), '[]') "
                               "FROM turns t JOIN conversation_threads ct ON ct.conversation_id = t.conversation_id "
                               "WHERE t.author = 'ashley' AND NOT t.follows")
        return [(th, tx) for th, tx in got]

    def waiting(self) -> list[tuple[int, datetime]]:
        got = scalar(self.url, "SELECT coalesce(json_agg(json_build_array(id, due_at) ORDER BY id), '[]') "
                               "FROM wakes WHERE settled_at IS NULL")
        return [(int(i), datetime.fromisoformat(d)) for i, d in got]

    def outcome(self, wake_id: int) -> str | None:
        return scalar(self.url, "SELECT outcome FROM wakes WHERE id = %s", (wake_id,))

    def work_rows(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM turn_work"))


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    model = Model()
    w = World(url, home, alana, sam, model, PostgresWakes(db))
    people = (Person(alana, home, "Alana"), Person(sam, home, "Sam"))
    services.register(People, Home(Household(home, "home", "America/Denver", "", people)))
    services.register(Presence, Nobody())
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, 60.0))
    services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
    services.register(Tools, Switchboard())
    services.register(Inference, model)
    services.register(Wakes, w.wakes)
    services.register(Initiative, Initiative.null())
    try:
        yield w
    finally:
        for interface in (People, Presence, Conversations, InFlight, Outbox, Tools, Inference, Wakes, Initiative):
            services.unregister(interface)
        await db.close()


def test_a_one_off_fires_once_at_its_time_with_no_tools_and_goes_out_though_initiative_would_keep_quiet(
        db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            later = await w.remind(due_at=datetime.now(UTC) + timedelta(hours=1))
            assert await runner.sweep() == 0 and w.model.prompts == []
            scalar(db_url, "WITH u AS (UPDATE wakes SET due_at = now() - interval '1 second' RETURNING 1) "
                           "SELECT count(*) FROM u")
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            [prompt] = w.model.prompts
            said = [m.text for m in prompt.messages if isinstance(m, Message)][-1]
            assert BRIEF in said
            assert w.answers() == [(f"push:{w.alana}", SAYS.text)]
            assert w.outcome(later) == "turn" and w.waiting() == [] and w.work_rows() == 0
            assert await runner.sweep() == 0 and len(w.model.prompts) == 1
    run(go())


def test_a_reminder_for_another_person_reaches_their_phone_alone(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.remind(w.sam, by=w.alana)
            w.model.script = [SAYS]
            await runner.sweep()
            assert w.answers() == [(f"push:{w.sam}", SAYS.text)]
    run(go())


def test_the_fired_turn_reaches_only_the_person_it_is_for() -> None:
    inbound = reminder_turn.inbound(7, Reminder(1, 2, 3, BRIEF, datetime.now(UTC), None), Person(2, 1, "Sam"),
                                    Person(3, 1, "Alana"))
    assert owner_alone(inbound) and inbound.thread == "push:2" and inbound.speaker_id == 2
    assert inbound.device_id is None and inbound.place is None and inbound.reads_only
    assert inbound.unprompted and inbound.promised and not inbound.remembers and inbound.source == "wake:7"


def test_a_monthly_occurrence_fires_once_and_its_next_is_nine_local_on_the_first(db_url: str) -> None:
    monthly = Repeat("monthly", 1, datetime(2026, 10, 1, 9, 0))

    async def go() -> None:
        async with world(db_url) as w:
            first = await w.remind(repeat=monthly)
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            [(nxt, due_at)] = w.waiting()
            local = due_at.astimezone(DENVER)
            assert nxt != first and (local.day, local.hour, local.minute) == (1, 9, 0)
            assert due_at > datetime.now(UTC) and w.outcome(first) == "turn"
            assert await runner.sweep() == 0

            scalar(db_url, "WITH u AS (UPDATE wakes SET due_at = now() - interval '1 second' WHERE id = %s "
                           "RETURNING 1) SELECT count(*) FROM u", (nxt,))
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            assert len(w.waiting()) == 1 and w.outcome(nxt) == "turn"
            assert w.answers() == [(f"push:{w.alana}", SAYS.text)] * 2
    run(go())


def test_two_runners_at_once_fire_an_occurrence_once_and_schedule_one_next(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.remind(repeat=Repeat("daily", 1, datetime(2026, 10, 1, 9, 0)))
            w.model.script = [SAYS, SAYS]
            await asyncio.gather(runner.sweep(), runner.sweep())
            assert len(w.model.prompts) == 1
            assert w.answers() == [(f"push:{w.alana}", SAYS.text)] and len(w.waiting()) == 1
    run(go())


def test_a_runner_killed_mid_turn_is_finished_by_the_resumer_and_the_occurrence_fires_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            first = await w.remind(repeat=Repeat("monthly", 1, datetime(2026, 10, 1, 9, 0)))
            w.model.hang = True
            sweeping = asyncio.create_task(runner.sweep())
            await asyncio.wait_for(w.model.reached.wait(), 10)
            sweeping.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sweeping
            assert w.work_rows() == 1 and w.answers() == [] and w.outcome(first) is None

            scalar(db_url, "WITH u AS (UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second' "
                           "RETURNING 1) SELECT count(*) FROM u")
            w.model.hang = False
            w.model.script = [SAYS]
            assert await resume.sweep() == 1
            assert w.answers() == [(f"push:{w.alana}", SAYS.text)]

            assert await runner.sweep() == 1
            assert w.answers() == [(f"push:{w.alana}", SAYS.text)] and w.outcome(first) == "turn"
            assert len(w.waiting()) == 1 and await runner.sweep() == 0
    run(go())


def test_occurrences_missed_in_an_outage_fire_once_late_then_wait_for_the_next(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            missed = await w.remind(due_at=datetime.now(UTC) - timedelta(days=95),
                                    repeat=Repeat("monthly", 1, datetime(2026, 7, 1, 9, 0)))
            w.model.script = [SAYS, SAYS, SAYS]
            assert await runner.sweep() == 1
            assert await runner.sweep() == 0
            assert len(w.model.prompts) == 1 and w.outcome(missed) == "turn"
            [(_, due_at)] = w.waiting()
            assert datetime.now(UTC) < due_at < datetime.now(UTC) + timedelta(days=32)
    run(go())


def test_a_cancelled_repeating_reminder_never_fires_again(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            first = await w.remind(repeat=Repeat("daily", 1, datetime(2026, 10, 1, 9, 0)))
            w.model.script = [SAYS]
            await runner.sweep()
            [(nxt, _)] = w.waiting()
            assert await w.wakes.cancel(w.home, w.alana, nxt)
            scalar(db_url, "WITH u AS (UPDATE wakes SET due_at = now() - interval '1 second' WHERE id = %s "
                           "RETURNING 1) SELECT count(*) FROM u", (nxt,))
            assert await runner.sweep() == 0
            assert w.waiting() == [] and len(w.model.prompts) == 1 and w.outcome(first) == "turn"
    run(go())


def test_an_occurrence_refused_every_time_settles_failed_and_the_series_goes_on(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            first = await w.remind(repeat=Repeat("daily", 1, datetime(2026, 10, 1, 9, 0)))
            w.model.script = [InferenceRefused("no")] * runner.CONFIG.fire_attempts
            for _ in range(runner.CONFIG.fire_attempts):
                scalar(db_url, "WITH u AS (UPDATE wakes SET due_at = now() - interval '1 second' WHERE id = %s "
                               "RETURNING 1) SELECT count(*) FROM u", (first,))
                assert await runner.sweep() == 1
            assert w.outcome(first) == "failed" and w.answers() == [] and len(w.waiting()) == 1
    run(go())


def test_no_log_line_carries_what_the_reminder_says(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            await w.remind(w.sam, by=w.alana, repeat=Repeat("monthly", 1, datetime(2026, 10, 1, 9, 0)))
            w.model.script = [SAYS]
            await runner.sweep()
    run(go())
    out = capsys.readouterr().out
    [settled] = events(out, "wakes.settled")
    assert settled["outcome"] == "turn" and settled["kind"] == "reminder"
    for value in ("NGFCU", "1,234", "Proton", "Visa", "Alana", "Sam"):
        assert value not in out, value
