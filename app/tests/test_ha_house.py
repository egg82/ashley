"""`HaHouse` over a stand-in Home Assistant (a real HTTP and WebSocket server): states with their area and names, the
registries as neutral records, actions (and the one that returns data only), history and the logbook, automation and
script configs, helpers, registry changes in Home Assistant's own names, and the failures the House port promises."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley.home_assistant.client import connect
from ashley.home_assistant.ha_house import HaHouse
from ashley.home_assistant.house import HouseRejected, HouseUnavailable, Window
from ashley.home_assistant.house_settings import HouseSettings
from house_stand_support import TOKEN, Stand, serving

SETTINGS = HouseSettings(timeout_s=5.0, socket_max_bytes=1_000_000)
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def world() -> Stand:
    stand = Stand()
    stand.states = [
        {"entity_id": "light.front_porch", "state": "off", "attributes": {"friendly_name": "Front Porch"},
         "last_changed": "2026-11-01T10:00:00+00:00"},
        {"entity_id": "sensor.rack", "state": "21", "attributes": {"friendly_name": "Rack"}, "last_changed": None},
        {"entity_id": "automation.arrive", "state": "on", "attributes": {"friendly_name": "Arrival", "id": "arrive"}},
        {"entity_id": "script.night", "state": "off", "attributes": {"friendly_name": "Night"}}]
    stand.registries = {
        "area": [{"area_id": "porch", "name": "Porch", "aliases": ["front porch"], "floor_id": "ground"},
                 {"area_id": "attic", "name": "Attic", "aliases": [], "floor_id": None}],
        "floor": [{"floor_id": "ground", "name": "Ground", "level": 0, "aliases": []}],
        "label": [{"label_id": "x", "name": "Xmas", "description": "lights"}],
        "device": [{"id": "d1", "name": "Echo", "name_by_user": None, "area_id": "attic", "manufacturer": "Espressif",
                    "model": "m5stack-atom", "sw_version": "2026.9.2", "config_entries": ["e1"], "disabled_by": None}],
        "entity": [
            {"entity_id": "light.front_porch", "name": None, "original_name": "Front Porch", "area_id": "porch",
             "device_id": None, "platform": "template", "disabled_by": None, "hidden_by": None,
             "options": {"conversation": {"should_expose": True}}, "config_entry_id": None, "has_entity_name": False},
            {"entity_id": "sensor.rack", "name": None, "original_name": "Rack", "area_id": None, "device_id": "d1",
             "platform": "esphome", "disabled_by": None, "hidden_by": "user", "options": {}, "config_entry_id": "e1",
             "has_entity_name": True}]}
    stand.entries = [{"entry_id": "e1", "title": "Echo", "domain": "esphome", "state": "loaded", "disabled_by": None}]
    stand.aliases = {"light.front_porch": [None, "porch light"]}
    stand.helpers = {"input_boolean": [{"id": "guest", "name": "Guest"}]}
    stand.automations = {"arrive": {"id": "arrive", "alias": "Arrival"}}
    stand.services = [
        {"domain": "light", "services": {"turn_on": {"description": "on", "fields": {"brightness_pct": {"description": "b"}}}}},
        {"domain": "calendar", "services": {"get_events": {"fields": {}, "response": {"optional": False}}}}]
    stand.diagnostics = {"e1": {"data": {"bluetooth_proxy_feature_flags": 0}}}
    return stand


def run[T](stand: Stand, work: Callable[[HaHouse], Awaitable[T]], token: str = TOKEN) -> T:
    async def go() -> T:
        with serving(stand) as base:
            client = connect(base, token)
            try:
                return await work(HaHouse(client, SETTINGS))
            finally:
                await client.http.aclose()
    return asyncio.run(go())


def test_a_state_carries_its_area_its_names_and_whether_the_household_lists_it() -> None:
    states = {s.id: s for s in run(world(), lambda h: h.states())}
    porch = states["light.front_porch"]
    assert (porch.name, porch.area, porch.aliases, porch.area_aliases, porch.featured) == (
        "Front Porch", "Porch", ("porch light",), ("front porch",), True)
    assert states["sensor.rack"].area == "Attic" and states["sensor.rack"].featured is False
    assert states["sensor.rack"].changed is None and porch.changed is not None


def test_records_are_neutral_for_every_kind() -> None:
    stand = world()
    got = run(stand, lambda h: _records(h))
    assert got["entity"]["sensor.rack"].fields["name"] == "Echo Rack" and got["entity"]["sensor.rack"].fields["hidden"] is True
    assert got["device"]["d1"].fields["integration"] == "esphome" and got["device"]["d1"].fields["integration_ids"] == ["e1"]
    assert got["device"]["d1"].fields["area"] == "Attic" and got["device"]["d1"].fields["model"] == "m5stack-atom"
    assert got["area"]["porch"].fields["floor"] == "Ground" and got["floor"]["ground"].fields["level"] == 0
    assert got["label"]["x"].name == "Xmas" and got["integration"]["e1"].fields["domain"] == "esphome"
    assert got["entity"]["light.front_porch"].fields["exposed"] is True and got["entity"]["light.front_porch"].fields["aliases"] == ["porch light"]


async def _records(house: HaHouse) -> dict[str, dict[str, Any]]:
    return {k: {r.id: r for r in await house.records(k)} for k in ("entity", "device", "area", "floor", "label", "integration")}


def test_every_call_carries_the_bearer_token_on_rest_and_websocket() -> None:
    stand = world()
    run(stand, lambda h: h.states())
    kinds = {kind for kind, _, _ in stand.calls}
    assert kinds == {"rest", "ws"} and {bearer for _, _, bearer in stand.calls} == {f"Bearer {TOKEN}"}


def test_a_refused_token_is_unavailable_not_an_empty_house() -> None:
    with pytest.raises(HouseUnavailable):
        run(world(), lambda h: h.states(), token="wrong")


def test_an_action_runs_on_the_ids_and_reports_what_changed() -> None:
    stand = world()
    done = run(stand, lambda h: h.perform("light.turn_on", ("light.front_porch",), {"brightness_pct": 30}))
    assert [s.id for s in done.changed] == ["light.front_porch"] and done.response is None
    assert stand.posted == [("light/turn_on", {"brightness_pct": 30, "entity_id": ["light.front_porch"]}, {})]


def test_an_action_that_only_returns_data_is_asked_again_for_its_response() -> None:
    stand = world()
    done = run(stand, lambda h: h.perform("calendar.get_events", ("calendar.home",), {}))
    assert done.response == {"answer": 42}
    assert [q for _, _, q in stand.posted] == [{}, {"return_response": "1"}]


def test_a_refusal_by_the_house_is_a_rejection_with_its_reason() -> None:
    stand = world()
    stand.reject = "no such thing"
    with pytest.raises(HouseRejected, match="no such thing"):
        run(stand, lambda h: h.perform("light.turn_on", ("light.front_porch",), {}))


def test_history_and_logbook_read_the_named_things() -> None:
    stand = world()
    window = Window(NOW - timedelta(hours=2), NOW, ("light.front_porch",))
    series = run(stand, lambda h: h.history(window))
    assert [(s.id, [r.state for r in s.readings]) for s in series] == [("light.front_porch", ["off"])]
    entries = run(stand, lambda h: h.logbook(window))
    assert [(e.id, e.message) for e in entries] == [("light.front_porch", "turned on")]
    with pytest.raises(HouseRejected):
        run(stand, lambda h: h.history(Window(NOW, NOW)))


def test_automations_scripts_and_helpers_list_read_write_and_delete() -> None:
    stand = world()

    async def work(house: HaHouse) -> tuple[Any, ...]:
        listed = (await house.configs("automation"), await house.configs("script"), await house.configs("helper"))
        read = await house.config("automation", "arrive")
        missing = await house.config("script", "nope")
        wrote = await house.write_config("script", "night", {"alias": "Night", "sequence": []})
        made = await house.write_config("helper", None, {"type": "input_boolean", "name": "Movie night"})
        gone = (await house.delete_config("automation", "arrive"), await house.delete_config("automation", "arrive"))
        return listed, read, missing, wrote, made, gone, await house.config("helper", "input_boolean:guest")

    listed, read, missing, wrote, made, gone, helper = run(stand, work)
    assert [i.id for i in listed[0]] == ["arrive"] and [i.id for i in listed[1]] == ["night"]
    assert [i.id for i in listed[2]] == ["input_boolean:guest"]
    assert read == {"id": "arrive", "alias": "Arrival"} and missing is None
    assert wrote == "night" and stand.scripts["night"]["alias"] == "Night"
    assert made == "input_boolean:movie_night" and gone == (True, False)
    assert helper == {"type": "input_boolean", "id": "guest", "name": "Guest"}


def test_a_new_automation_is_named_by_its_alias_and_never_takes_an_id_in_use() -> None:
    stand = world()

    async def work(house: HaHouse) -> tuple[str, str, str]:
        first = await house.write_config("automation", None, {"alias": "Arrival!"})
        again = await house.write_config("automation", None, {"alias": "Arrival!"})
        taken = await house.write_config("automation", None, {"alias": "arrive"})
        return first, again, taken

    assert run(stand, work) == ("arrival", "arrival_2", "arrive_2")
    assert stand.automations["arrive"] == {"id": "arrive", "alias": "Arrival"}
    with pytest.raises(HouseRejected, match="alias"):
        run(stand, lambda h: h.write_config("script", None, {"sequence": []}))


def test_a_config_home_assistant_refuses_is_a_rejection_and_nothing_is_written() -> None:
    stand = world()
    stand.reject = "invalid trigger"
    with pytest.raises(HouseRejected, match="invalid trigger"):
        run(stand, lambda h: h.write_config("automation", "bad", {"alias": "x"}))
    assert "bad" not in stand.automations


def test_a_registry_change_uses_home_assistants_names() -> None:
    stand = world()

    async def work(house: HaHouse) -> None:
        await house.update_record("entity", "light.front_porch", {
            "name": "Porch", "aliases": ["veranda"], "area": "Attic", "disabled": True, "exposed": False})

    run(stand, work)
    updates = [c for c in stand.commands if c["type"] == "config/entity_registry/update"]
    assert updates == [{"id": updates[0]["id"], "type": "config/entity_registry/update", "entity_id": "light.front_porch",
                        "name": "Porch", "aliases": [None, "veranda"], "area_id": "attic", "disabled_by": "user"}]
    [expose] = [c for c in stand.commands if c["type"] == "homeassistant/expose_entity"]
    assert expose["should_expose"] is False and expose["entity_ids"] == ["light.front_porch"]


@pytest.mark.parametrize(("kind", "fields", "says"), [
    ("entity", {"colour": "red"}, "no colour to set"), ("area", {"floor": "Basement"}, "no floor named Basement"),
    ("integration", {"name": "x"}, "cannot be changed")])
def test_a_change_to_a_field_a_record_lacks_is_rejected_before_anything_is_sent(kind: Any, fields: dict[str, Any], says: str) -> None:
    stand = world()
    with pytest.raises(HouseRejected, match=says):
        run(stand, lambda h: h.update_record(kind, "light.front_porch", fields))
    assert not [c for c in stand.commands if "update" in c["type"]]


def test_records_are_created_and_deleted_and_an_integration_removed() -> None:
    stand = world()

    async def work(house: HaHouse) -> None:
        await house.create_record("area", {"name": "Garage", "aliases": ["carport"], "floor": "Ground"})
        await house.delete_record("entity", "sensor.rack")
        await house.delete_record("device", "d1")
        await house.delete_record("integration", "e1")

    run(stand, work)
    kinds = [c["type"] for c in stand.commands]
    assert "config/area_registry/create" in kinds and "config/entity_registry/remove" in kinds
    assert "config/device_registry/remove_config_entry" in kinds and stand.entries == []
    [created] = [c for c in stand.commands if c["type"] == "config/area_registry/create"]
    assert created["floor_id"] == "ground" and created["aliases"] == ["carport"]


def test_diagnostics_are_the_integrations_own_report_or_none() -> None:
    stand = world()
    got = run(stand, lambda h: asyncio.gather(h.diagnostics("e1"), h.diagnostics("nope")))
    assert got == [{"data": {"bluetooth_proxy_feature_flags": 0}}, None]


def test_actions_name_their_fields_and_how_they_respond() -> None:
    actions = {a.name: a for a in run(world(), lambda h: h.actions())}
    assert actions["light.turn_on"].fields == {"brightness_pct": "b"} and actions["light.turn_on"].response == "none"
    assert actions["calendar.get_events"].response == "only"


def test_a_house_that_is_not_there_is_unavailable() -> None:
    async def go() -> None:
        client = connect("http://127.0.0.1:1", TOKEN)
        try:
            await HaHouse(client, SETTINGS).states()
        finally:
            await client.http.aclose()
    with pytest.raises(HouseUnavailable):
        asyncio.run(go())
