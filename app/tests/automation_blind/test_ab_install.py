"""An accepted Install written to the fake Home Assistant, and the Undo of it taken back out: exactly what was written,
turned on or off and restored, recorded before the first write, never repeated, and never over an automation this bench
did not install."""

from ab_support import CONFIG, add, Seen, body, bench_with_piece, carried, crowd, edit, install, installed, propose, undo
from ashley import services
from ashley.home_assistant.homes import Homes
from ashley.workshop.commands import Installed, Uninstalled
from ashley.workshop.install_piece import automation_id_for, carry_out
from ashley.workshop.installs import Installs, NewInstall
from ashley.workshop.workshop import Workshop
from automations_support import FakeHouse
from homes_support import AnyHousehold
from contract.conversations_support import db_url as db_url, run

OLD = "automation.old_porch"


def house_with_old(on: bool = True) -> FakeHouse:
    house = FakeHouse()
    house.add("old_porch", "Old porch", on=on, triggers=[{"trigger": "time", "at": "01:00:00"}])
    house.add("other", "Unrelated", on=True)
    return house


def test_a_fresh_install_writes_the_pieces_config_under_its_id_and_leaves_it_off_as_proposed(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, record = await installed(c.alana, bench, piece, enabled=False)
            ident = automation_id_for(bench, piece)
            assert house.configs == {ident: {"id": ident, **CONFIG}}
            assert house.enabled == {house.entity_of(ident): False}
            assert record is not None and record.ending == "done"
            assert (record.started.action, record.started.piece_id, record.started.bench_id, record.started.seq,
                    record.started.automation_id, record.started.enabled) == ("install", piece, bench, seq, ident, False)

    run(scenario())


def test_a_fresh_install_proposed_enabled_is_left_on(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            await installed(c.alana, bench, piece, enabled=True)
            assert house.enabled == {house.entity_of(automation_id_for(bench, piece)): True}

    run(scenario())


def test_the_install_effect_names_what_was_proposed(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url, house_with_old()) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1, True, OLD))
            applied = await services.get(Workshop).apply(c.alana, bench, install(c.alana, bench, proposed.seq, piece))
            assert applied.effect == Installed(piece, 1, automation_id_for(bench, piece), True, OLD, proposed.seq)

    run(scenario())


def test_the_named_old_automation_is_turned_off_and_nothing_else_of_the_house_changes(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        async with crowd(db_url, house) as (_, c):
            old_config, other_config = dict(house.configs["old_porch"]), dict(house.configs["other"])
            bench, piece = await bench_with_piece(c.alana)
            _, _, record = await installed(c.alana, bench, piece, enabled=True, turn_off=OLD)
            assert record is not None and record.ending == "done" and record.started.turn_off == OLD
            assert house.enabled[OLD] is False and house.enabled["automation.other"] is True
            assert house.enabled[house.entity_of(automation_id_for(bench, piece))] is True
            assert house.configs["old_porch"] == old_config and house.configs["other"] == other_config
            assert set(house.configs) == {"old_porch", "other", automation_id_for(bench, piece)}
            assert {path for method, path in house.writes if method == "DELETE"} == set()

    run(scenario())


def test_an_install_naming_no_old_automation_leaves_every_other_automation_as_it_was(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            await installed(c.alana, bench, piece, enabled=False)
            assert house.enabled[OLD] is True and house.enabled["automation.other"] is True

    run(scenario())


def test_a_reinstall_after_edits_updates_the_same_automation_id(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            await installed(c.alana, bench, piece, enabled=True)
            await services.get(Workshop).apply(c.alana, bench, edit(c.alana, piece, 1, alias="porch v2"))
            await installed(c.alana, bench, piece, version=2, enabled=True)
            ident = automation_id_for(bench, piece)
            assert list(house.configs) == [ident]
            assert house.configs[ident] == {"id": ident, **CONFIG, "alias": "porch v2"}
            assert house.enabled == {house.entity_of(ident): True}

    run(scenario())


def test_two_pieces_install_under_two_ids(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, first = await bench_with_piece(c.alana)
            second = (await services.get(Workshop).apply(c.alana, bench, add(c.alana, body(alias="b")))).piece_id
            assert second is not None
            await installed(c.alana, bench, first)
            await installed(c.alana, bench, second)
            assert set(house.configs) == {automation_id_for(bench, first), automation_id_for(bench, second)}
            assert house.configs[automation_id_for(bench, second)]["alias"] == "b"
            assert house.configs[automation_id_for(bench, first)]["alias"] == CONFIG["alias"]

    run(scenario())


def test_undo_of_a_fresh_install_deletes_it_and_turns_the_old_automation_back_on(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old(on=True)
        async with crowd(db_url, house) as (_, c):
            before = dict(house.configs)
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece, enabled=True, turn_off=OLD)
            assert house.enabled[OLD] is False
            applied, record = await carried(c.alana, bench, undo(c.alana, seq))
            assert applied.outcome == "accepted"
            assert applied.effect == Uninstalled(piece, seq, automation_id_for(bench, piece))
            assert record is not None and record.ending == "done" and record.started.action == "uninstall"
            assert (record.started.turn_off, record.started.piece_id, record.started.automation_id) == (
                OLD, piece, automation_id_for(bench, piece))
            assert house.configs == before and set(house.enabled) == {OLD, "automation.other"}
            assert house.enabled[OLD] is True and house.enabled["automation.other"] is True

    run(scenario())


def test_undo_leaves_an_old_automation_off_that_the_install_found_off(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old(on=False)
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece, turn_off=OLD)
            await carried(c.alana, bench, undo(c.alana, seq))
            assert house.enabled[OLD] is False
            assert set(house.configs) == {"old_porch", "other"}

    run(scenario())


def test_undo_of_an_install_that_named_no_old_automation_turns_nothing_on(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old(on=False)
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece)
            await carried(c.alana, bench, undo(c.alana, seq))
            assert house.enabled[OLD] is False and set(house.configs) == {"old_porch", "other"}

    run(scenario())


def test_undo_of_an_update_writes_back_the_config_and_on_off_state_the_house_had(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            await installed(c.alana, bench, piece, enabled=True)
            ident = automation_id_for(bench, piece)
            house.enabled[house.entity_of(ident)] = False
            first = dict(house.configs[ident])
            await services.get(Workshop).apply(c.alana, bench, edit(c.alana, piece, 1, alias="porch v2"))
            _, seq, _ = await installed(c.alana, bench, piece, version=2, enabled=True)
            assert house.enabled[house.entity_of(ident)] is True and house.configs[ident]["alias"] == "porch v2"
            _, record = await carried(c.alana, bench, undo(c.alana, seq))
            assert record is not None and record.ending == "done"
            assert house.configs == {ident: first} and house.enabled[house.entity_of(ident)] is False

    run(scenario())


def test_the_install_is_recorded_before_its_first_write_and_each_write_follows_the_record(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        async with crowd(db_url, house) as (_, c):
            seen = Seen(house.house())
            services.register(Homes, AnyHousehold(seen))
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1, False, OLD))
            applied = await services.get(Workshop).apply(c.alana, bench, install(c.alana, bench, proposed.seq, piece))
            seen.watch.append((c.alana.household_id, bench, applied.seq))
            record = await carry_out(c.alana, bench, applied)
            assert record is not None and record.ending == "done"
            assert seen.at_writes and seen.at_writes[0][0] == "write"
            assert all(stood == [True] for _, stood in seen.at_writes), seen.at_writes
            assert [name for name, _ in seen.at_writes][1:] == ["set_enabled", "set_enabled"]
            finished = await services.get(Installs).of(c.alana.household_id, bench, applied.seq)
            assert finished is not None and finished.ending == "done" and finished.finished_at is not None

    run(scenario())


def test_carrying_an_install_out_again_writes_nothing_and_returns_the_record_as_it_stands(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1, True, OLD))
            applied = await services.get(Workshop).apply(c.alana, bench, install(c.alana, bench, proposed.seq, piece))
            first = await carry_out(c.alana, bench, applied)
            writes, state = list(house.writes), (dict(house.configs), dict(house.enabled))
            house.enabled[OLD] = True
            again = await carry_out(c.alana, bench, applied)
            assert again == first and house.writes == writes
            assert house.configs == state[0] and house.enabled[OLD] is True

    run(scenario())


def test_carrying_an_undo_out_again_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece)
            applied, first = await carried(c.alana, bench, undo(c.alana, seq))
            writes = list(house.writes)
            ident = automation_id_for(bench, piece)
            house.add(ident, "someone put it back")
            assert await carry_out(c.alana, bench, applied) == first
            assert house.writes == writes and ident in house.configs

    run(scenario())


def test_an_install_whose_record_began_but_never_ended_is_not_carried_out(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1, True))
            applied = await services.get(Workshop).apply(c.alana, bench, install(c.alana, bench, proposed.seq, piece))
            ident = automation_id_for(bench, piece)
            await services.get(Installs).start(NewInstall(c.alana.household_id, bench, applied.seq, piece, "install",
                                                          ident, True, None, None, True))
            record = await carry_out(c.alana, bench, applied)
            assert record is not None and record.ending is None
            assert house.writes == [] and house.configs == {}

    run(scenario())


def test_a_command_that_is_not_an_install_or_an_undo_of_one_is_not_carried_out(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            for command in (propose(piece, 1, True, OLD), edit(c.alana, piece, 1, alias="x")):
                applied, record = await carried(c.alana, bench, command)
                assert applied.outcome == "accepted" and record is None
            assert house.writes == [] and house.enabled[OLD] is True

    run(scenario())


def test_an_install_never_writes_over_an_automation_under_its_id_that_this_bench_did_not_install(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            ident = automation_id_for(bench, piece)
            house.add(ident, "from another database's bench", on=True, marker="theirs")
            theirs, enabled = dict(house.configs[ident]), dict(house.enabled)
            _, seq, record = await installed(c.alana, bench, piece, enabled=False, turn_off=OLD)
            assert record is not None and record.ending == "failed" and record.note
            assert record.started.touched is False
            assert house.writes == [] and house.configs[ident] == theirs and house.enabled == enabled
            _, seq, again = await installed(c.alana, bench, piece, enabled=False, turn_off=OLD)
            assert again is not None and again.ending == "failed" and house.writes == []
            applied, undone = await carried(c.alana, bench, undo(c.alana, seq))
            assert applied.outcome == "accepted" and undone is not None and undone.ending == "done"
            assert house.writes == [] and house.configs[ident] == theirs and house.enabled == enabled

    run(scenario())


def test_an_install_may_update_an_automation_an_earlier_install_of_the_piece_wrote_even_if_it_changed_since(
        db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            await installed(c.alana, bench, piece, enabled=True)
            ident = automation_id_for(bench, piece)
            house.configs[ident] = {"id": ident, "alias": "edited in HA", "triggers": [], "actions": []}
            _, _, record = await installed(c.alana, bench, piece, enabled=True)
            assert record is not None and record.ending == "done" and house.configs[ident] == {"id": ident, **CONFIG}

    run(scenario())


def test_home_assistant_refusing_the_config_ends_the_install_refused_with_its_message_and_writes_nothing(
        db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        house.refuse = "extra keys not allowed @ data['bogus']"
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, record = await installed(c.alana, bench, piece, enabled=True, turn_off=OLD)
            assert record is not None and record.ending == "refused" and "bogus" in (record.note or "")
            assert set(house.configs) == {"old_porch", "other"} and house.enabled[OLD] is True
            house.refuse = None
            house.enabled[OLD] = False
            writes = list(house.writes)
            await carried(c.alana, bench, undo(c.alana, seq))
            assert house.writes == writes and set(house.configs) == {"old_porch", "other"}
            assert house.enabled[OLD] is False
            house.enabled[OLD] = True
            _, _, retry = await installed(c.alana, bench, piece, enabled=True, turn_off=OLD)
            assert retry is not None and retry.ending == "done"
            assert automation_id_for(bench, piece) in house.configs and house.enabled[OLD] is False

    run(scenario())


def test_home_assistant_out_of_reach_ends_the_install_failed_and_touches_nothing(db_url: str) -> None:
    async def scenario() -> None:
        house = house_with_old()
        house.down_after = 0
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, _, record = await installed(c.alana, bench, piece, enabled=True, turn_off=OLD)
            assert record is not None and record.ending == "failed" and record.note
            assert record.started.touched is False and house.writes == [] and house.enabled[OLD] is True

    run(scenario())


def test_an_install_carried_out_for_a_person_of_another_household_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            proposed = await services.get(Workshop).apply(c.alana, bench, propose(piece, 1))
            applied = await services.get(Workshop).apply(c.alana, bench, install(c.alana, bench, proposed.seq, piece))
            await carry_out(c.zed, bench, applied)
            assert house.writes == [] and house.configs == {}

    run(scenario())



def test_a_reinstall_after_an_undo_writes_a_fresh_automation(db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            _, seq, _ = await installed(c.alana, bench, piece, enabled=True)
            await carried(c.alana, bench, undo(c.alana, seq))
            assert house.configs == {}
            _, _, record = await installed(c.alana, bench, piece, enabled=True)
            ident = automation_id_for(bench, piece)
            assert record is not None and record.ending == "done" and house.configs == {ident: {"id": ident, **CONFIG}}

    run(scenario())


def test_an_install_that_could_not_reach_the_house_does_not_stop_a_later_install_updating_its_own_automation(
        db_url: str) -> None:
    async def scenario() -> None:
        house = FakeHouse()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            await installed(c.alana, bench, piece, enabled=True)
            house.down_after = len(house.requests)
            _, _, unreachable = await installed(c.alana, bench, piece, enabled=True)
            assert unreachable is not None and unreachable.ending == "failed"
            house.down_after = None
            await services.get(Workshop).apply(c.alana, bench, edit(c.alana, piece, 1, alias="v2"))
            _, _, record = await installed(c.alana, bench, piece, version=2, enabled=True)
            assert record is not None and record.ending == "done"
            assert house.configs[automation_id_for(bench, piece)]["alias"] == "v2"

    run(scenario())
