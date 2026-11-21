"""A shadow run installed through the Install path (`install_piece.carry_out`) over a real database and a fake HA: the
piece goes into HA under its own shadow id with its triggers and conditions kept, its alias marked and its actions
replaced by one event; nothing is turned off; the run is recorded before the house is written; the shadow never shows
as the piece's own install state and never blocks an undo of its other changes; its Undo deletes it and ends the run;
a refusal or a house out of reach ends the run at once."""

from datetime import timedelta

from ashley import services
from ashley.workshop import shadow
from ashley.workshop.commands import Edit, Installed, Undo
from ashley.workshop.install_piece import UNREACHABLE, automation_id_for, carry_out
from ashley.workshop.installs import Installs
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.shadows import Shadows
from ashley.workshop.workshop import Applied, Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from install_support import CONFIG, add, body, install, propose, world


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


async def shadowed(alana: Owner, turn_off: str | None = None) -> tuple[int, Applied]:
    """A bench with an automation piece (1), her shadow proposal (2) and the person's install of it (3)."""
    shop = services.get(Workshop)
    bench = await shop.open(alana, "b")
    await shop.apply(alana, bench.id, add(alana))
    await shop.apply(alana, bench.id, propose(turn_off=turn_off, shadow=True))
    return bench.id, await shop.apply(alana, bench.id, install(alana, bench.id, 2))


def test_a_shadows_id_is_never_the_real_automations() -> None:
    assert shadow.id_for("ashley_bench_4_piece_2") == "ashley_shadow_bench_4_piece_2"
    assert shadow.id_for("ashley_bench_4_piece_2") != "ashley_bench_4_piece_2"


def test_the_shadow_keeps_the_triggers_and_conditions_marks_the_alias_and_fires_one_event() -> None:
    config = shadow.config_of({**CONFIG, "variables": {"v": 1}}, 3, 1, 2)
    assert config["triggers"] == CONFIG["triggers"] and config["conditions"] == CONFIG["conditions"]
    assert config["mode"] == "single" and config["variables"] == {"v": 1}
    assert config["alias"] == shadow.MARK + CONFIG["alias"] and "description" not in config
    assert config["actions"] == [{"event": "ashley_shadow", "event_data": {"bench": 3, "piece": 1, "version": 2}}]


def test_a_shadow_install_writes_the_shadow_turns_nothing_off_and_leaves_the_pieces_own_state_alone(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()
    old = house.add("7e9f", "Alana is home")

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await shadowed(alana, turn_off=old)
            assert isinstance(applied.effect, Installed) and applied.effect.shadow and applied.effect.enabled
            record = await carry_out(alana, bench, applied)
            ident = shadow.id_for(automation_id_for(bench, 1))
            assert applied.effect.automation_id == ident
            assert set(house.configs) == {"7e9f", ident}
            assert house.configs[ident] == {"id": ident, **shadow.config_of(CONFIG, bench, 1, 1)}
            assert house.enabled == {old: True, house.entity_of(ident): True}
            assert record is not None and record.ending == "done" and record.started.shadow and record.started.turn_off is None
            assert await services.get(Installs).latest_on_bench(alana.household_id, bench) == {}
            runs = await services.get(Shadows).of_bench(alana.household_id, bench)
            began = runs[1]
            assert (began.started.install_seq, began.started.version, began.started.mirrors, began.ended_at) == (3, 1, old, None)
            assert began.started.person_id == alana.person_id and began.started.ends_at - began.started.started_at == timedelta(
                seconds=shadow.load().duration_s)
    run(scenario())


def test_a_shadow_is_undone_after_the_piece_was_edited_and_the_undo_deletes_it_and_ends_the_run(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench, applied = await shadowed(alana)
            await carry_out(alana, bench, applied)
            await shop.apply(alana, bench, Edit(By(alana.person_id), 1, 1, Text("porch", body(alias="second"))))
            undone = await shop.apply(alana, bench, Undo(By(alana.person_id), 3))
            assert undone.outcome == "accepted"
            record = await carry_out(alana, bench, undone)
            assert house.configs == {} and record is not None and record.ending == "done" and record.started.shadow
            run_ = (await services.get(Shadows).of_bench(alana.household_id, bench))[1]
            assert run_.ended_at is not None
    run(scenario())


def test_a_real_install_beside_a_shadow_keeps_its_own_state_and_an_edit_after_it_blocks_undoing_the_real_one(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            shop = services.get(Workshop)
            bench, applied = await shadowed(alana)
            await carry_out(alana, bench, applied)
            edit = await shop.apply(alana, bench, Edit(By(alana.person_id), 1, 1, Text("porch", body(alias="second"))))
            assert edit.outcome == "accepted"
            await shop.apply(alana, bench, propose(version=2, enabled=True))
            real = await carry_out(alana, bench, await shop.apply(alana, bench, install(alana, bench, 5)))
            assert real is not None and real.ending == "done" and not real.started.shadow
            ident = automation_id_for(bench, 1)
            assert ident in house.configs and shadow.id_for(ident) in house.configs
            latest = await services.get(Installs).latest_on_bench(alana.household_id, bench)
            assert latest[1].started.automation_id == ident
            assert (await services.get(Shadows).of_bench(alana.household_id, bench))[1].ended_at is None
            blocked = await shop.apply(alana, bench, Undo(By(alana.person_id), 4))
            assert blocked.outcome == "changed_since"
    run(scenario())


def test_a_shadow_run_does_not_block_undoing_an_edit_made_before_it(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url, FakeHouse()):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, add(alana))
            await shop.apply(alana, bench.id, Edit(By(alana.person_id), 1, 1, Text("porch", body(alias="second"))))
            await shop.apply(alana, bench.id, propose(version=2, shadow=True))
            applied = await shop.apply(alana, bench.id, install(alana, bench.id, 3))
            assert isinstance(applied.effect, Installed) and applied.effect.shadow
            assert (await shop.apply(alana, bench.id, Undo(By(alana.person_id), 2))).outcome == "accepted"
    run(scenario())


def test_an_install_of_a_proposal_that_is_not_a_shadow_has_no_run(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, add(alana))
            await shop.apply(alana, bench.id, propose())
            applied = await shop.apply(alana, bench.id, install(alana, bench.id, 2))
            assert isinstance(applied.effect, Installed) and not applied.effect.shadow
            assert isinstance(applied.effect.automation_id, str) and not applied.effect.automation_id.startswith("ashley_shadow")
            await carry_out(alana, bench.id, applied)
            assert await services.get(Shadows).of_bench(alana.household_id, bench.id) == {}
    run(scenario())


def test_a_refused_or_unreachable_shadow_install_ends_the_run_at_once(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        for house, ending in ((FakeHouse(refuse="not an automation"), "refused"), (FakeHouse(down_after=0), "failed")):
            async with world(db_url, house):
                bench, applied = await shadowed(alana)
                record = await carry_out(alana, bench, applied)
                assert record is not None and record.ending == ending
                assert house.configs == {}
                runs = await services.get(Shadows).of_bench(alana.household_id, bench)
                if ending == "refused":
                    assert runs[1].ended_at is not None
                else:
                    assert record.note == UNREACHABLE and runs == {}
    run(scenario())
