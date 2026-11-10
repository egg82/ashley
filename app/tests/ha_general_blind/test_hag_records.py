"""HaHouse's record writes against a stand-in Home Assistant: areas, floors and labels created, the named fields of an
entity, device, area, floor or label changed and no others, and removals (`house.House.create_record`, `update_record`,
`delete_record`)."""

import pytest
from ashley.home_assistant.house import HouseRejected, HouseUnavailable, RecordKind
from contract.conversations_support import run
from hag_state_support import Ha
from hag_support import furnish, make_house


def test_areas_floors_and_labels_are_created_with_their_fields_and_found_in_the_records(ha: Ha) -> None:
    async def go() -> None:
        house = make_house(ha)
        area = await house.create_record("area", {"name": "Sauna", "aliases": ["steam room"]})
        floor = await house.create_record("floor", {"name": "Basement", "level": -1})
        label = await house.create_record("label", {"name": "Guest"})
        assert {r.id: r.name for r in await house.records("area")} == {area: "Sauna"}
        assert {r.id: r.name for r in await house.records("floor")} == {floor: "Basement"}
        assert {r.id: r.name for r in await house.records("label")} == {label: "Guest"}
        (got,) = await house.records("area")
        assert list(got.fields["aliases"]) == ["steam room"]
        (basement,) = await house.records("floor")
        assert basement.fields["level"] == -1
    run(go())


def test_an_area_created_on_a_named_floor_lands_on_it(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        house = make_house(ha)
        area = await house.create_record("area", {"name": "Study", "floor": "Ground floor"})
        got = {r.id: r for r in await house.records("area")}[area]
        assert got.fields["floor"] in ("Ground floor", "ground_floor")
        assert ha.areas[area]["floor_id"] == "ground_floor"
    run(go())


@pytest.mark.parametrize("kind", ["device", "entity", "integration"])
def test_only_an_area_a_floor_or_a_label_can_be_created(ha: Ha, kind: RecordKind) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseRejected):
            await make_house(ha).create_record(kind, {"name": "Thing"})
    run(go())
    assert ha.mutations() == []


def test_a_record_the_house_refuses_to_create_is_rejected_and_nothing_is_added(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseRejected):
            await make_house(ha).create_record("area", {"name": "Kitchen"})
    run(go())
    assert set(ha.areas) == {"living_room", "kitchen"}


def test_update_changes_the_named_fields_of_an_entity_and_no_others(ha: Ha) -> None:
    furnish(ha)
    before = dict(ha.entities["light.reading_lamp"])

    async def go() -> None:
        await make_house(ha).update_record("entity", "light.reading_lamp", {"name": "Bedside lamp"})
    run(go())
    row = ha.entities["light.reading_lamp"]
    assert row["name"] == "Bedside lamp"
    assert {k: v for k, v in row.items() if k != "name"} == {k: v for k, v in before.items() if k != "name"}


def test_an_entitys_aliases_are_written_keeping_its_own_name(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        await make_house(ha).update_record("entity", "light.reading_lamp", {"aliases": ["night light", "lamp"]})
        got = {s.id: s for s in await make_house(ha).states()}["light.reading_lamp"]
        assert set(got.aliases) == {"night light", "lamp"}
    run(go())
    assert "Reading lamp" in ha.names_of("light.reading_lamp")
    assert set(ha.names_of("light.reading_lamp")) == {"Reading lamp", "night light", "lamp"}


def test_clearing_an_entitys_aliases_keeps_its_own_name(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        await make_house(ha).update_record("entity", "light.reading_lamp", {"aliases": []})
    run(go())
    assert ha.names_of("light.reading_lamp") == ["Reading lamp"]


def test_an_entity_is_moved_to_an_area_by_name_and_flags_are_set(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        house = make_house(ha)
        await house.update_record("entity", "light.kitchen_strip", {"area": "Living room"})
        await house.update_record("entity", "light.kitchen_strip", {"disabled": True, "hidden": True})
        got = {r.id: r for r in await house.records("entity")}["light.kitchen_strip"]
        assert got.fields["disabled"] is True and got.fields["hidden"] is True
        await house.update_record("entity", "light.kitchen_strip", {"disabled": False})
        again = {r.id: r for r in await house.records("entity")}["light.kitchen_strip"]
        assert again.fields["disabled"] is False and again.fields["hidden"] is True
    run(go())
    row = ha.entities["light.kitchen_strip"]
    assert row["area_id"] == "living_room" and row["disabled_by"] is None and row["hidden_by"] is not None


def test_an_entity_is_exposed_to_the_assistant_and_withdrawn(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        house = make_house(ha)
        await house.update_record("entity", "light.kitchen_strip", {"exposed": True})
        assert {s.id: s.featured for s in await house.states()}["light.kitchen_strip"] is True
        await house.update_record("entity", "light.kitchen_strip", {"exposed": False})
        assert {s.id: s.featured for s in await house.states()}["light.kitchen_strip"] is False
    run(go())


def test_a_device_is_renamed_and_the_records_show_the_new_name(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        await make_house(ha).update_record("device", "dev_hue_lamp", {"name": "Hall lamp"})
        (device,) = await make_house(ha).records("device")
        assert device.name == "Hall lamp"
    run(go())


def test_a_devices_area_changes_and_nothing_else(ha: Ha) -> None:
    furnish(ha)
    before = dict(ha.devices["dev_hue_lamp"])

    async def go() -> None:
        await make_house(ha).update_record("device", "dev_hue_lamp", {"area": "Kitchen"})
    run(go())
    row = ha.devices["dev_hue_lamp"]
    assert row["area_id"] == "kitchen"
    for kept in ("manufacturer", "model", "sw_version", "config_entries", "disabled_by"):
        assert row[kept] == before[kept]


def test_an_area_update_changes_only_what_it_names(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        await make_house(ha).update_record("area", "living_room", {"name": "Lounge room"})
    run(go())
    row = ha.areas["living_room"]
    assert row["name"] == "Lounge room" and row["aliases"] == ["lounge"] and row["floor_id"] == "ground_floor"


def test_an_area_update_of_aliases_and_a_floor_leaves_its_name(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        await make_house(ha).update_record("area", "kitchen", {"aliases": ["cookery"], "floor": "Ground floor"})
    run(go())
    row = ha.areas["kitchen"]
    assert row["name"] == "Kitchen" and row["aliases"] == ["cookery"] and row["floor_id"] == "ground_floor"


def test_a_floor_and_a_label_update_leave_the_rest(ha: Ha) -> None:
    furnish(ha)
    ha.label("Security")

    async def go() -> None:
        house = make_house(ha)
        await house.update_record("floor", "ground_floor", {"level": 1})
        await house.update_record("label", "security", {"name": "Safety"})
    run(go())
    assert ha.floors["ground_floor"]["level"] == 1 and ha.floors["ground_floor"]["name"] == "Ground floor"
    assert ha.labels["security"]["name"] == "Safety"


def test_updating_what_is_not_there_or_a_field_that_cannot_be_set_is_rejected(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        house = make_house(ha)
        with pytest.raises(HouseRejected):
            await house.update_record("entity", "light.no_such", {"name": "x"})
        with pytest.raises(HouseRejected):
            await house.update_record("area", "no_such_area", {"name": "x"})
        with pytest.raises(HouseRejected):
            await house.update_record("entity", "light.reading_lamp", {"state": "on"})
    run(go())
    assert ha.states["light.reading_lamp"]["state"] == "off"


@pytest.mark.parametrize("kind,table,ident", [("area", "areas", "kitchen"), ("floor", "floors", "ground_floor"),
                                              ("label", "labels", "security")])
def test_a_registry_record_is_deleted_and_a_second_delete_is_rejected(ha: Ha, kind: RecordKind, table: str, ident: str) -> None:
    furnish(ha)
    ha.label("Security")

    async def go() -> None:
        house = make_house(ha)
        await house.delete_record(kind, ident)
        assert ident not in {r.id for r in await house.records(kind)}
        with pytest.raises(HouseRejected):
            await house.delete_record(kind, ident)
    run(go())
    assert ident not in getattr(ha, table)


def test_an_entity_is_deleted_from_the_registry(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        await make_house(ha).delete_record("entity", "light.kitchen_strip")
        assert "light.kitchen_strip" not in {r.id for r in await make_house(ha).records("entity")}
        with pytest.raises(HouseRejected):
            await make_house(ha).delete_record("entity", "light.kitchen_strip")
    run(go())
    assert "light.kitchen_strip" not in ha.entities and "light.reading_lamp" in ha.entities


def test_an_integration_is_removed(ha: Ha) -> None:
    furnish(ha)
    ha.entry("mqtt", "Mosquitto")

    async def go() -> None:
        await make_house(ha).delete_record("integration", "entry_hue_bridge")
        assert {r.id for r in await make_house(ha).records("integration")} == {"entry_mosquitto"}
    run(go())


def test_removing_an_integration_that_is_not_there_is_the_houses_refusal_not_its_absence(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseRejected):
            await make_house(ha).delete_record("integration", "entry_no_such")
    run(go())


def test_a_device_is_removed_from_every_config_entry_it_belongs_to(ha: Ha) -> None:
    furnish(ha)
    ha.entry("mqtt", "Mosquitto")
    ha.devices["dev_hue_lamp"]["config_entries"].append("entry_mosquitto")
    ha.device("Other lamp", entries=("entry_hue_bridge",))

    async def go() -> None:
        await make_house(ha).delete_record("device", "dev_hue_lamp")
        assert {r.id for r in await make_house(ha).records("device")} == {"dev_other_lamp"}
        with pytest.raises(HouseRejected):
            await make_house(ha).delete_record("device", "dev_hue_lamp")
    run(go())
    assert set(ha.entries) == {"entry_hue_bridge", "entry_mosquitto"}


def test_a_registry_command_the_house_fails_on_is_unavailable_for_a_change(ha: Ha) -> None:
    furnish(ha)
    ha.ws_drop = True

    async def go() -> None:
        with pytest.raises(HouseUnavailable):
            await make_house(ha).create_record("area", {"name": "Attic"})
    run(go())
    assert "attic" not in ha.areas


def test_moving_a_thing_to_an_area_the_house_does_not_have_is_rejected_and_leaves_its_area(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseRejected):
            await make_house(ha).update_record("entity", "light.kitchen_strip", {"area": "Nowhere"})
        with pytest.raises(HouseRejected):
            await make_house(ha).update_record("device", "dev_hue_lamp", {"area": "Nowhere"})
    run(go())
    assert ha.entities["light.kitchen_strip"]["area_id"] == "kitchen" and ha.devices["dev_hue_lamp"]["area_id"] == "living_room"


def test_a_refusal_of_an_integration_removal_carries_the_houses_own_message(ha: Ha) -> None:
    furnish(ha)
    ha.status = 400

    async def go() -> None:
        with pytest.raises(HouseRejected) as raised:
            await make_house(ha).delete_record("integration", "entry_hue_bridge")
        assert str(raised.value) == "broken"
    run(go())


def test_a_command_the_house_answers_with_a_failure_is_its_refusal_with_its_message(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseRejected) as raised:
            await make_house(ha).delete_record("entity", "light.no_such_lamp")
        assert str(raised.value) == "Entity not found"
    run(go())
