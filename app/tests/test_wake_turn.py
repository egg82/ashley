"""A wake becoming her own turn, over a real database: the `wakes` singleton's sweep takes each due wake, finds the
household's one wake rule for its event on an open bench, and runs her turn through the shared turn loop with the
rule's brief and only its tools; Initiative lets what she says out through the outbox, to the phone of the person the
wake is about, only when her reply's `worth_saying` is true. One event however often it arrives, and a wake handed in
again after its turn, is one turn; a turn killed part way is finished by the `inflight` resumer and goes out once."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from ashley import logs, services
from ashley.channels import resume
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.wake import runner
from ashley.channels.unprompted import QUIET
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, Prompt, ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative, WorthSaying
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.presence import Presence
from ashley.senses.wakes import Wake, Wakes
from ashley.tools.tools import Tools
from ashley.workshop.commands import Add, Command
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import load as workshop_rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import events, person, run, scalar
from wake_support import LOOK, Model, Nobody, Switchboard

SAYS = Reply(spoken="Welcome home.", text="Welcome home, Alana.", worth_saying=True)
QUIETLY = Reply(spoken="Nothing to say.", text="Nothing to say.", worth_saying=False)
BRIEF = "Greet him only if he has been away a while."


@dataclass
class OnePerson(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        if (system, external_id) == ("home_assistant", "person.alana"):
            return self.home.people[0]
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class World:
    url: str
    home: int
    alana: int
    device: int
    model: Model
    tools: Switchboard
    wakes: Wakes
    workshop: Workshop

    async def rule(self, event: str = "alana_arrived", tools: tuple[str, ...] = ("switch",), *,
                   closed: bool = False) -> None:
        owner = Owner(self.home, self.alana)
        bench = await self.workshop.open(owner, "arrivals")
        body = json.dumps({"event": event, "brief": BRIEF, "tools": list(tools)})
        command: Command = Add(By(self.alana), "wake", Text("arrival", body), "medium")
        await self.workshop.apply(owner, bench.id, command)
        if closed:
            await self.workshop.close(owner, bench.id)

    async def woken(self, event_id: str = "ctx-1", event: str = "alana_arrived", who: str | None = "person.alana",
                    at: datetime | None = None) -> int:
        made = await self.wakes.receive(self.device, Wake(self.home, event_id, event, who, "front_door",
                                                          at or datetime.now(UTC)))
        return made.id

    def queued(self) -> list[tuple[str, str]]:
        got = scalar(self.url, "SELECT coalesce(json_agg(json_build_array(thread, body) ORDER BY id), '[]') "
                               "FROM outbox")
        return [(t, b) for t, b in got]

    def hers(self) -> list[str]:
        got = scalar(self.url, "SELECT coalesce(json_agg(text ORDER BY id), '[]') FROM turns WHERE author = 'ashley'")
        return list(got)

    def outcome(self, wake_id: int) -> str | None:
        return scalar(self.url, "SELECT outcome FROM wakes WHERE id = %s", (wake_id,))

    def work_rows(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM turn_work"))


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana = person(url, home, "Alana")
    device = int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                             "VALUES (%s, 'home assistant', 'house', 'household', 'text', 'chat', "
                             "decode(%s, 'hex')) RETURNING id", (home, f"{home:064x}")))
    model, tools = Model(), Switchboard()
    w = World(url, home, alana, device, model, tools, PostgresWakes(db), PostgresWorkshop(db, workshop_rules()))
    services.register(People, OnePerson(Household(home, "home", "America/Denver", "", (Person(alana, home, "Alana"),))))
    services.register(Presence, Nobody())
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, 60.0))
    services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
    services.register(Tools, tools)
    services.register(Inference, model)
    services.register(Wakes, w.wakes)
    services.register(Workshop, w.workshop)
    services.register(Initiative, WorthSaying())
    try:
        yield w
    finally:
        for interface in (People, Presence, Conversations, InFlight, Outbox, Tools, Inference, Wakes, Workshop,
                          Initiative):
            services.unregister(interface)
        await db.close()


def first_message(prompt: Prompt) -> str:
    texts = [m.text for m in prompt.messages if isinstance(m, Message)]
    return texts[-1]


def test_a_wake_with_a_rule_is_one_turn_whose_reply_goes_to_their_phone_when_worth_saying(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            wake_id = await w.woken()
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            [prompt] = w.model.prompts
            said = first_message(prompt)
            assert BRIEF in said and "alana_arrived" in said and "front_door" in said
            assert [t.name for t in prompt.tools] == ["switch"]
            assert w.queued() == [(f"push:{w.alana}", SAYS.text)]
            assert w.hers() == [SAYS.text]
            assert w.outcome(wake_id) == "turn" and w.work_rows() == 0
            assert await runner.sweep() == 0 and len(w.model.prompts) == 1
    run(go())


def test_the_wake_is_stored_as_a_turn_of_the_household_with_no_speaker_and_only_its_event_fields_never_her_brief(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            wake_id = await w.woken()
            w.model.script = [SAYS]
            await runner.sweep()
            rows = scalar(db_url, "SELECT json_agg(json_build_array(author, speaker_id, source, text) ORDER BY id) "
                                  "FROM turns")
            [said, hers] = rows
            assert said[:3] == ["household", None, f"wake:{wake_id}"]
            assert said[3] == "alana_arrived · Alana · front_door"
            assert BRIEF not in said[3] and "worth_saying" not in said[3]
            [prompt] = w.model.prompts
            assert BRIEF in first_message(prompt) and "worth_saying" in first_message(prompt)
            assert hers[0] == "ashley"
            assert scalar(db_url, "SELECT count(*) FROM turns WHERE author = 'person'") == 0
    run(go())


def test_a_reply_not_worth_saying_is_stored_as_her_staying_quiet_and_nothing_goes_out(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            wake_id = await w.woken()
            w.model.script = [QUIETLY]
            assert await runner.sweep() == 1
            assert w.queued() == [] and w.hers() == [QUIET]
            assert w.outcome(wake_id) == "turn"
    run(go())


def test_an_unwired_initiative_never_speaks(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            services.register(Initiative, Initiative.null())
            await w.rule()
            await w.woken()
            w.model.script = [SAYS]
            await runner.sweep()
            assert w.queued() == [] and w.hers() == [QUIET]
    run(go())


def test_one_event_arriving_twice_and_a_wake_handed_in_again_are_one_turn(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            first = await w.woken()
            assert await w.woken() == first
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            scalar(db_url, "WITH u AS (UPDATE wakes SET settled_at = NULL, outcome = NULL RETURNING 1) "
                           "SELECT count(*) FROM u")
            assert await runner.sweep() == 1
            assert len(w.model.prompts) == 1 and w.queued() == [(f"push:{w.alana}", SAYS.text)]
            assert w.hers() == [SAYS.text] and w.outcome(first) == "turn"
    run(go())


def test_a_turn_killed_part_way_is_finished_by_the_resumer_and_goes_out_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule(tools=("look", "switch"))
            wake_id = await w.woken()
            w.model.hang = True
            w.model.script = [ToolCalls((ToolCall("c1", "look", {}),))]
            sweeping = asyncio.create_task(runner.sweep())
            await asyncio.wait_for(w.model.reached.wait(), 10)
            sweeping.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sweeping
            assert w.work_rows() == 1 and w.queued() == [] and w.outcome(wake_id) is None

            scalar(db_url, "WITH u AS (UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second' "
                           "RETURNING 1) SELECT count(*) FROM u")
            w.model.hang = False
            w.model.script = [SAYS]
            assert await resume.sweep() == 1
            assert w.queued() == [(f"push:{w.alana}", SAYS.text)] and w.work_rows() == 0
            assert [c.id for c in w.tools.ran] == ["c1"]

            assert await runner.sweep() == 1
            assert w.queued() == [(f"push:{w.alana}", SAYS.text)] and w.hers() == [SAYS.text]
            assert w.outcome(wake_id) == "turn"
    run(go())


@pytest.mark.parametrize("case", ["no_rule", "closed_bench", "other_event", "ambiguous", "no_person", "unmapped",
                                  "expired"])
def test_a_wake_she_cannot_act_on_is_settled_with_why_and_runs_no_turn(db_url: str, case: str) -> None:
    expected = {"closed_bench": "no_rule", "other_event": "no_rule", "unmapped": "no_person"}.get(case, case)

    async def go() -> None:
        async with world(db_url) as w:
            if case != "no_rule":
                await w.rule(closed=case == "closed_bench", event="garage_open" if case == "other_event" else
                             "alana_arrived")
            if case == "ambiguous":
                await w.rule()
            who = {"no_person": None, "unmapped": "person.elodie"}.get(case, "person.alana")
            at = datetime.now(UTC) - timedelta(hours=1) if case == "expired" else None
            wake_id = await w.woken(who=who, at=at)
            if case == "expired":
                scalar(db_url, "WITH u AS (UPDATE wakes SET received_at = received_at - interval '1 hour', "
                               "due_at = due_at - interval '1 hour' RETURNING 1) SELECT count(*) FROM u")
            assert await runner.sweep() == 1
            assert w.model.prompts == [] and w.outcome(wake_id) == expected and w.queued() == []
    run(go())


def test_a_wake_turn_never_holds_on_a_reply_that_is_not_the_answer(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule(tools=("look",))
            wake_id = await w.woken()
            checking = Reply(answers=False, spoken="Let me check.", text="Let me check.")
            w.model.script = [checking, ToolCalls((ToolCall("c1", "look", {}),)), SAYS]
            await runner.sweep()
            assert w.hers() == [SAYS.text] and w.queued() == [(f"push:{w.alana}", SAYS.text)]
            assert w.outcome(wake_id) == "turn" and w.work_rows() == 0
    run(go())


def test_a_turn_that_cannot_run_now_leaves_the_wake_due_and_a_later_sweep_runs_it_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            wake_id = await w.woken()
            w.model.script = [InferenceUnavailable("down")]
            assert await runner.sweep() == 1
            assert w.outcome(wake_id) is None and w.queued() == [] and w.work_rows() == 0
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            assert w.outcome(wake_id) == "turn" and w.hers() == [SAYS.text]
            assert w.queued() == [(f"push:{w.alana}", SAYS.text)]
            assert await runner.sweep() == 0
    run(go())


def test_a_turn_the_model_refuses_settles_the_wake_failed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            wake_id = await w.woken()
            w.model.script = [InferenceRefused("no")]
            assert await runner.sweep() == 1
            assert w.outcome(wake_id) == "failed" and w.queued() == [] and w.hers() == []
    run(go())


def test_the_rule_tools_are_the_only_ones_she_may_call(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule(tools=("look",))
            await w.woken()
            w.model.script = [ToolCalls((ToolCall("c1", "switch", {}),)), SAYS]
            await runner.sweep()
            assert w.tools.ran == []
            assert [t.name for t in w.model.prompts[0].tools] == [LOOK.name]
    run(go())


def test_the_sweep_logs_ids_and_counts_never_a_field_of_the_wake(db_url: str,
                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            await w.woken()
            w.model.script = [SAYS]
            await runner.sweep()
    run(go())
    out = capsys.readouterr().out
    [settled] = events(out, "wakes.settled")
    [decided] = events(out, "initiative.decided")
    assert settled["outcome"] == "turn" and decided["speaks"] == "true"
    lines = [line for line in out.splitlines() if "event=wakes." in line or "event=initiative." in line]
    for line in lines:
        for value in ("alana", "front_door", "ctx-1", "Greet", "Welcome"):
            assert value not in line, line
