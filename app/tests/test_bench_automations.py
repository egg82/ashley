"""Her Home Assistant automation tools on a bench (`ashley.tools.bench_automations.BenchAutomationTools`), over a real
database and a fake HA: offered only while a house is wired; the house's automations listed and one read as a piece's
body; a proposal is a Propose by her that writes nothing to the house, refused with its hint; where an install stands
read back; and her Install or Undo of an install refused `needs_person`."""

import asyncio
import json
from typing import Any

from ashley import services
from ashley.home_assistant.homes import Homes
from ashley.people.model import Household
from ashley.people.people import People
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_automations import BenchAutomationTools
from ashley.tools.bench_results import HINTS
from ashley.workshop import automation_config
from ashley.workshop.commands import REASONS, Install, Undo
from ashley.workshop.install_piece import carry_out
from ashley.workshop.model import HER, Owner
from ashley.workshop.workshop import Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from one_home_support import OneHome
from install_support import AnyHousehold, add, body, install, world


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


async def ask(tools: BenchAutomationTools, name: str, **arguments: object) -> ToolResult:
    return await tools.call(ToolCall("c1", name, arguments))


def loaded(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    got: dict[str, Any] = json.loads(result.content)
    return got


def test_every_reason_has_a_hint() -> None:
    assert set(HINTS) == set(REASONS)


def test_nothing_is_offered_while_no_house_is_wired() -> None:
    services.unregister(Homes)
    catalogue = asyncio.run(BenchAutomationTools(1, 2, 3).catalogue())
    assert catalogue.specs == () and catalogue.instructions is None


def test_she_lists_the_houses_automations_and_reads_one_as_a_pieces_body(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()
    house.add("7e9f", "Alana is home", on=False, description="d", trigger=[{"trigger": "state"}],
              action=[{"action": "notify.alana"}])

    async def scenario() -> None:
        async with world(db_url, house):
            services.register(People, OneHome(Household(alana.household_id, "home", "America/Denver", "", ())))
            bench = await services.get(Workshop).open(alana, "b")
            tools = BenchAutomationTools(alana.household_id, alana.person_id, bench.id)
            names = [s.name for s in (await tools.catalogue()).specs]
            assert names == ["house_automations", "house_automation", "bench_propose_install", "bench_install_state"]
            listed = loaded(await ask(tools, "house_automations"))["automations"]
            assert listed == [{"automation_id": "7e9f", "entity_id": "automation.7e9f", "name": "Alana is home",
                               "enabled": False, "last_triggered": "Mon 12 Oct 2026 22:30"}]
            read = loaded(await ask(tools, "house_automation", automation_id="7e9f"))
            assert read["kind"] == "automation" and read["alias"] == "Alana is home"
            assert json.loads(read["body"]) == {"alias": "Alana is home", "description": "d",
                                                "triggers": [{"trigger": "state"}],
                                                "actions": [{"action": "notify.alana"}]}
            assert automation_config.well_formed(read["body"])
            missing = await ask(tools, "house_automation", automation_id="nope")
            assert missing.is_error and missing.content.startswith("no_such_automation:")
            assert house.writes == []
            services.unregister(People)

    run(scenario())


def test_her_proposal_writes_nothing_to_the_house_and_waits_on_the_person(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()
    old = house.add("7e9f", "Alana is home")

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, add(alana))
            tools = BenchAutomationTools(alana.household_id, alana.person_id, bench.id)
            got = loaded(await ask(tools, "bench_propose_install", piece_id=1, base_version=1, enabled=True,
                                   turn_off=old))
            assert got["seq"] == 2
            assert house.writes == []
            state = loaded(await ask(tools, "bench_install_state", piece_id=1))
            assert state == {"piece_id": 1, "last": None,
                             "waiting_on_approval": {"seq": 2, "version": 1, "enabled": True, "turn_off": old}}
            view = await shop.read(alana, bench.id)
            assert view.proposals[1].seq == 2 and view.recent[-1].by == HER

    run(scenario())


def test_her_proposal_refusals_come_back_with_their_hints(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, add(alana, body(actions=[])))
            tools = BenchAutomationTools(alana.household_id, alana.person_id, bench.id)
            incomplete = await ask(tools, "bench_propose_install", piece_id=1, base_version=1, enabled=False)
            assert incomplete.is_error and incomplete.content == f"incomplete: {HINTS['incomplete']}"
            stale = await ask(tools, "bench_propose_install", piece_id=1, base_version=9, enabled=False)
            assert stale.is_error and stale.content.startswith("stale_base:")
            unknown = await ask(tools, "bench_propose_install", piece_id=1, base_version=1, enabled=False,
                                turn_off="automation.nope")
            assert unknown.is_error and unknown.content.startswith("no_such_automation:")
            bad = await ask(tools, "bench_propose_install", piece_id=1, base_version=1, enabled="yes")
            assert bad.is_error and bad.content.startswith("bad_arguments:")
            assert house.writes == []

    run(scenario())


def test_she_cannot_install_or_undo_an_install_only_the_person_can(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, add(alana))
            tools = BenchAutomationTools(alana.household_id, alana.person_id, bench.id)
            await ask(tools, "bench_propose_install", piece_id=1, base_version=1, enabled=False)
            hers = await shop.apply(alana, bench.id, Install(HER, 1, 2, "x"))
            assert hers.outcome == "needs_person"
            theirs = await shop.apply(alana, bench.id, install(alana, bench.id, 2))
            record = await carry_out(alana, bench.id, theirs)
            assert record is not None and record.ending == "done"
            assert (await shop.apply(alana, bench.id, Undo(HER, theirs.seq))).outcome == "needs_person"
            state = loaded(await ask(tools, "bench_install_state", piece_id=1))
            assert state["waiting_on_approval"] is None
            assert state["last"]["action"] == "install" and state["last"]["ending"] == "done"

    run(scenario())


def _instructions(house: FakeHouse) -> str:
    services.register(Homes, AnyHousehold(house.client()))
    got = asyncio.run(BenchAutomationTools(1, 2, 3).catalogue()).instructions
    assert got is not None
    return got


def test_her_automation_guidance_gives_the_exact_wake_action_and_never_sends_her_to_ask_about_it() -> None:
    from ashley.tools.bench_automation_specs import LOOK_FIRST
    text = _instructions(FakeHouse())
    assert 'rest_command.ashley_wake' in text and 'event_id' in text and '{{ context.id }}' in text
    assert 'who' in text and 'person.' in text
    assert LOOK_FIRST in text


def test_the_house_is_asked_for_its_services_once_however_often_the_turn_reads_the_catalogue() -> None:
    house = FakeHouse(wake=True)
    services.register(Homes, AnyHousehold(house.client()))
    tools = BenchAutomationTools(1, 2, 3)
    asyncio.run(tools.catalogue())
    asyncio.run(tools.catalogue())
    assert house.requests.count(("GET", "/api/services")) == 1


def test_her_automation_guidance_says_from_the_house_whether_the_wake_is_wired() -> None:
    from ashley.tools.bench_automation_specs import WIRED, NOT_WIRED, UNKNOWN
    assert WIRED in _instructions(FakeHouse(wake=True)) and NOT_WIRED not in _instructions(FakeHouse(wake=True))
    assert NOT_WIRED in _instructions(FakeHouse(wake=False))
    assert UNKNOWN in _instructions(FakeHouse(wake=True, down_after=0))
