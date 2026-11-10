"""Carrying an install out on the house (`ashley.workshop.install_piece.carry_out`) over a real database and a fake HA:
an install writes the piece's config under the piece's id, on or off as proposed, and turns the old automation off;
its undo deletes a fresh install, writes an update's earlier config back, and turns the old one on again only if it
was on; each is recorded before its first write and when it ends, and never carried out twice; a refusal or a house
out of reach is an ending in the record, and an install that wrote nothing has nothing to undo."""

from ashley import services
from ashley.live.events import BenchChanged, Shown
from ashley.workshop.commands import Edit, Undo
from ashley.workshop.install_piece import CHANGED, NOTHING, TAKEN, UNREACHABLE, automation_id_for, carry_out
from ashley.workshop.installs import Installs, InstallRecord
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.workshop import Applied, Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from install_support import CONFIG, add, body, install, propose, world


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


async def installed(alana: Owner, enabled: bool = False, turn_off: str | None = None) -> tuple[int, Applied]:
    """A bench with an automation piece (1), her proposal (2) and the person's install of it (3), applied."""
    shop = services.get(Workshop)
    bench = await shop.open(alana, "b")
    await shop.apply(alana, bench.id, add(alana))
    await shop.apply(alana, bench.id, propose(enabled=enabled, turn_off=turn_off))
    return bench.id, await shop.apply(alana, bench.id, install(alana, bench.id, 2))


async def undo(alana: Owner, bench: int, seq: int) -> InstallRecord | None:
    return await carry_out(alana, bench, await services.get(Workshop).apply(alana, bench, Undo(By(alana.person_id), seq)))


def test_an_install_writes_the_config_under_the_pieces_id_disabled_and_turns_the_old_one_off(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()
    old = house.add("7e9f", "Alana is home")

    async def scenario() -> None:
        async with world(db_url, house) as w:
            bench, applied = await installed(alana, turn_off=old)
            record = await carry_out(alana, bench, applied)
            ident = automation_id_for(bench, 1)
            assert house.configs[ident] == {"id": ident, **CONFIG}
            assert house.enabled == {house.entity_of(ident): False, old: False}
            assert record is not None and record.ending == "done" and record.note is None
            began = record.started
            assert (began.seq, began.action, began.automation_id, began.enabled, began.turn_off, began.touched) == (
                3, "install", ident, False, old, True)
            assert began.before is not None and began.before.config is None and began.before.turn_off_was_on is True
            assert w.heard.events[-1] == BenchChanged(Shown(alana.household_id, alana.person_id), bench, 3)

    run(scenario())


def test_an_enabled_install_is_left_on(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, enabled=True)
            await carry_out(alana, bench, applied)
            assert house.enabled == {house.entity_of(automation_id_for(bench, 1)): True}

    run(scenario())


def test_undoing_a_fresh_install_deletes_it_and_turns_the_old_one_back_on(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()
    old = house.add("7e9f", "Alana is home")

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, turn_off=old)
            await carry_out(alana, bench, applied)
            record = await undo(alana, bench, 3)
            assert set(house.configs) == {"7e9f"} and house.enabled == {old: True}
            assert record is not None and record.ending == "done"
            assert (record.started.action, record.started.seq, record.started.turn_off) == ("uninstall", 4, old)

    run(scenario())


def test_an_old_automation_that_was_off_stays_off_after_the_undo(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()
    old = house.add("7e9f", "Alana is home", on=False)

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, turn_off=old)
            await carry_out(alana, bench, applied)
            await undo(alana, bench, 3)
            assert house.enabled == {old: False}
            assert ("POST", "/api/services/automation/turn_on") not in house.writes

    run(scenario())


def test_a_second_install_updates_the_same_id_and_its_undo_writes_the_earlier_config_back(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench, applied = await installed(alana, enabled=True)
            await carry_out(alana, bench, applied)
            ident = automation_id_for(bench, 1)
            await shop.apply(alana, bench, Edit(By(alana.person_id), 1, 1, Text("porch", body(alias="second"))))
            await shop.apply(alana, bench, propose(version=2, enabled=False))
            second = await carry_out(alana, bench, await shop.apply(alana, bench, install(alana, bench, 5)))
            assert second is not None and second.ending == "done"
            assert house.configs[ident]["alias"] == "second" and house.enabled[house.entity_of(ident)] is False
            assert second.started.before is not None and second.started.before.config == {"id": ident, **CONFIG}
            assert second.started.before.enabled is True
            await undo(alana, bench, 6)
            assert house.configs[ident] == {"id": ident, **CONFIG} and house.enabled[house.entity_of(ident)] is True

    run(scenario())


def test_a_refused_config_ends_refused_with_has_reason_and_its_undo_writes_nothing(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse(refuse="Message malformed: extra keys not allowed")
    old = house.add("7e9f", "Alana is home")

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, turn_off=old)
            record = await carry_out(alana, bench, applied)
            assert record is not None and (record.ending, record.note) == ("refused", house.refuse)
            assert house.enabled == {old: True} and set(house.configs) == {"7e9f"}
            writes = len(house.writes)
            taken_back = await undo(alana, bench, 3)
            assert taken_back is not None and (taken_back.ending, taken_back.note) == ("done", NOTHING)
            assert len(house.writes) == writes

    run(scenario())


def test_a_house_out_of_reach_before_anything_is_written_is_recorded_failed_and_touches_nothing(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse(down_after=0)

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana)
            record = await carry_out(alana, bench, applied)
            assert record is not None and (record.ending, record.note, record.started.touched) == (
                "failed", UNREACHABLE, False)
            assert house.writes == []
            house.down_after = None
            taken_back = await undo(alana, bench, 3)
            assert taken_back is not None and taken_back.note == NOTHING and house.writes == []

    run(scenario())


def test_a_house_that_stops_answering_part_way_says_from_which_step_and_is_still_taken_back(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana)
            house.down_after = len(house.requests) + 4
            record = await carry_out(alana, bench, applied)
            assert record is not None and record.ending == "failed" and record.note is not None
            assert "(turn off)" in record.note
            house.down_after = None
            await undo(alana, bench, 3)
            assert house.configs == {}

    run(scenario())


def test_an_install_is_never_carried_out_twice(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana)
            first = await carry_out(alana, bench, applied)
            writes = len(house.writes)
            again = await carry_out(alana, bench, applied)
            assert len(house.writes) == writes
            assert again == first

    run(scenario())


def test_a_piece_changed_before_it_reached_the_house_writes_nothing(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench, applied = await installed(alana)
            await shop.apply(alana, bench, Edit(By(alana.person_id), 1, 1, Text("porch", body(alias="x"))))
            record = await carry_out(alana, bench, applied)
            assert record is not None and (record.ending, record.note) == ("failed", CHANGED)
            assert house.writes == []

    run(scenario())


def test_any_other_command_is_not_carried_out(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            added = await shop.apply(alana, bench.id, add(alana))
            proposed = await shop.apply(alana, bench.id, propose())
            assert await carry_out(alana, bench.id, added) is None
            assert await carry_out(alana, bench.id, proposed) is None
            assert house.requests == []
            assert await services.get(Installs).latest_on_bench(alana.household_id, bench.id) == {}

    run(scenario())


def test_an_automation_under_the_pieces_id_that_this_bench_never_installed_is_never_overwritten(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            ident = automation_id_for(bench.id, 1)
            house.add(ident, "someone else's")
            await shop.apply(alana, bench.id, add(alana))
            await shop.apply(alana, bench.id, propose())
            record = await carry_out(alana, bench.id, await shop.apply(alana, bench.id, install(alana, bench.id, 2)))
            assert record is not None and (record.ending, record.note, record.started.touched) == (
                "failed", TAKEN, False)
            assert house.configs[ident]["alias"] == "someone else's" and house.writes == []

    run(scenario())


def test_a_refused_install_undone_then_installed_again_still_never_overwrites_a_foreign_automation(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            ident = automation_id_for(bench.id, 1)
            house.add(ident, "someone else's")
            await shop.apply(alana, bench.id, add(alana))
            await shop.apply(alana, bench.id, propose())
            await carry_out(alana, bench.id, await shop.apply(alana, bench.id, install(alana, bench.id, 2)))
            await undo(alana, bench.id, 3)
            await shop.apply(alana, bench.id, propose())
            again = await carry_out(alana, bench.id, await shop.apply(alana, bench.id, install(alana, bench.id, 5)))
            assert again is not None and (again.ending, again.note) == ("failed", TAKEN)
            assert house.configs[ident]["alias"] == "someone else's" and house.writes == []

    run(scenario())


def test_an_install_after_a_refused_update_still_updates_what_an_earlier_install_wrote(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench, applied = await installed(alana)
            await carry_out(alana, bench, applied)
            ident = automation_id_for(bench, 1)
            house.refuse = "Message malformed"
            await shop.apply(alana, bench, propose())
            refused = await carry_out(alana, bench, await shop.apply(alana, bench, install(alana, bench, 4)))
            assert refused is not None and refused.ending == "refused"
            await undo(alana, bench, 5)
            house.refuse = None
            await shop.apply(alana, bench, Edit(By(alana.person_id), 1, 1, Text("porch", body(alias="third"))))
            await shop.apply(alana, bench, propose(version=2))
            third = await carry_out(alana, bench, await shop.apply(alana, bench, install(alana, bench, 8)))
            assert third is not None and third.ending == "done" and house.configs[ident]["alias"] == "third"

    run(scenario())
