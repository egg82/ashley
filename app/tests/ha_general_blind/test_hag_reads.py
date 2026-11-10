"""HaHouse's reads against a stand-in Home Assistant: states with areas and names resolved, the registries as neutral
records, history, logbook, the actions on offer, and how a failure is told apart (`house.House`, `ha_house.HaHouse`)."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from ashley.home_assistant.house import RECORD_KINDS, HouseRejected, HouseUnavailable, NullHouse, Window
from contract.conversations_support import run
from hag_state_support import T0, TOKEN, Ha
from hag_support import furnish, make_house


def test_offered_is_true_and_the_null_house_offers_nothing_and_raises_everywhere() -> None:
    async def go() -> None:
        assert make_house(Ha(url="http://127.0.0.1:9")).offered()
        null = NullHouse()
        assert not null.offered()
        with pytest.raises(HouseUnavailable):
            await null.states()
        with pytest.raises(HouseUnavailable):
            await null.records("area")
        with pytest.raises(HouseUnavailable):
            await null.perform("light.turn_on", (), {})
        with pytest.raises(HouseUnavailable):
            await null.delete_config("automation", "x")
    run(go())


def test_states_carry_the_entities_with_their_areas_names_and_changed_time(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        got = {s.id: s for s in await make_house(ha).states()}
        assert set(got) == {"light.reading_lamp", "light.kitchen_strip", "sensor.attic_temperature"}
        lamp = got["light.reading_lamp"]
        assert (lamp.name, lamp.state, lamp.domain) == ("Reading lamp", "off", "light")
        assert lamp.changed == T0
        assert got["sensor.attic_temperature"].attributes["unit_of_measurement"] == "C"
    run(go())


def test_an_entity_with_no_area_of_its_own_has_its_devices_and_one_with_neither_has_none(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        got = {s.id: s for s in await make_house(ha).states()}
        assert got["light.reading_lamp"].area == "Living room"
        assert got["light.reading_lamp"].area_aliases == ("lounge",)
        assert got["light.kitchen_strip"].area == "Kitchen"
        assert got["light.kitchen_strip"].area_aliases == ()
        assert got["sensor.attic_temperature"].area is None
    run(go())


def test_an_entitys_own_area_wins_over_its_devices(ha: Ha) -> None:
    furnish(ha)
    ha.entities["light.reading_lamp"]["area_id"] = "kitchen"

    async def go() -> None:
        got = {s.id: s for s in await make_house(ha).states()}
        assert got["light.reading_lamp"].area == "Kitchen"
    run(go())


def test_changed_is_none_when_the_house_does_not_say(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        got = {s.id: s for s in await make_house(ha).states()}
        assert got["sensor.attic_temperature"].changed is None
    run(go())


def test_aliases_are_the_other_names_and_not_the_entitys_own(ha: Ha) -> None:
    furnish(ha)
    ha.add("light.hall", "off", "Hall light", aliases=["corridor light"])

    async def go() -> None:
        got = {s.id: s for s in await make_house(ha).states()}
        assert got["light.reading_lamp"].aliases == ("book light",)
        assert got["light.kitchen_strip"].aliases == ()
        assert "Hall light" not in got["light.hall"].aliases
        assert "corridor light" in got["light.hall"].aliases
    run(go())


def test_featured_is_what_the_household_exposes(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        got = {s.id: s for s in await make_house(ha).states()}
        assert got["light.reading_lamp"].featured is True
        assert got["light.kitchen_strip"].featured is False
        assert got["sensor.attic_temperature"].featured is False
    run(go())


def test_an_empty_house_has_no_states(ha: Ha) -> None:
    async def go() -> None:
        assert await make_house(ha).states() == ()
    run(go())


def test_every_record_kind_is_listed_with_ids_and_names(ha: Ha) -> None:
    furnish(ha)
    ha.label("Security")

    async def go() -> None:
        house = make_house(ha)
        names = {kind: {r.id: r.name for r in await house.records(kind)} for kind in RECORD_KINDS}
        assert names["area"] == {"living_room": "Living room", "kitchen": "Kitchen"}
        assert names["floor"] == {"ground_floor": "Ground floor"}
        assert names["label"] == {"security": "Security"}
        assert names["device"] == {"dev_hue_lamp": "Hue lamp"}
        assert names["integration"] == {"entry_hue_bridge": "Hue bridge"}
        assert names["entity"]["light.reading_lamp"] == "Reading lamp"
        assert set(names["entity"]) == {"light.reading_lamp", "light.kitchen_strip"}
    run(go())


def test_records_carry_the_fields_the_port_documents(ha: Ha) -> None:
    furnish(ha)
    ha.devices["dev_hue_lamp"]["disabled_by"] = "user"
    ha.entities["light.kitchen_strip"]["hidden_by"] = "user"

    async def go() -> None:
        house = make_house(ha)
        (device,) = await house.records("device")
        assert (device.fields["manufacturer"], device.fields["model"], device.fields["version"]) == ("Signify", "LCT015", "1.2")
        assert device.fields["disabled"] is True
        assert device.fields["area"] in ("Living room", "living_room")
        ha.entry("mqtt", "Mosquitto", state="setup_error")
        by_id = {r.id: r for r in await house.records("integration")}
        assert by_id["entry_mosquitto"].fields["state"] == "setup_error"
        integration = by_id["entry_hue_bridge"]
        assert (integration.fields["title"], integration.fields["domain"], integration.fields["state"]) == ("Hue bridge", "hue", "loaded")
        assert integration.fields["disabled"] is False
        entities = {r.id: r for r in await house.records("entity")}
        assert entities["light.kitchen_strip"].fields["hidden"] is True
        assert entities["light.reading_lamp"].fields["hidden"] is False
        assert entities["light.reading_lamp"].fields["exposed"] is True
        assert entities["light.kitchen_strip"].fields["exposed"] is False
        assert entities["light.reading_lamp"].fields["domain"] == "light"
        assert entities["light.reading_lamp"].fields["area"] in ("Living room", "living_room")
        assert entities["light.kitchen_strip"].fields["area"] in ("Kitchen", "kitchen")
        assert "book light" in entities["light.reading_lamp"].fields["aliases"]
        areas = {r.id: r for r in await house.records("area")}
        assert list(areas["living_room"].fields["aliases"]) == ["lounge"]
        assert areas["living_room"].fields["floor"] in ("Ground floor", "ground_floor")
        (floor,) = await house.records("floor")
        assert floor.fields["level"] == 0
    run(go())


def test_a_device_the_household_renamed_shows_its_new_name(ha: Ha) -> None:
    furnish(ha)
    ha.devices["dev_hue_lamp"]["name_by_user"] = "Hall lamp"

    async def go() -> None:
        (device,) = await make_house(ha).records("device")
        assert device.name == "Hall lamp" and device.fields["name"] == "Hall lamp"
    run(go())


def test_a_record_kind_with_nothing_in_it_is_an_empty_tuple(ha: Ha) -> None:
    async def go() -> None:
        for kind in RECORD_KINDS:
            assert await make_house(ha).records(kind) == ()
    run(go())


def window(*ids: str, start: datetime = T0, hours: int = 6) -> Window:
    return Window(start, start + timedelta(hours=hours), ids)


def test_history_is_each_requested_things_readings_in_the_window_and_no_others(ha: Ha) -> None:
    furnish(ha)
    ha.history["light.reading_lamp"] = [(T0 + timedelta(hours=1), "on"), (T0 + timedelta(hours=2), "off"),
                                        (T0 + timedelta(hours=9), "on")]
    ha.history["light.kitchen_strip"] = [(T0 + timedelta(minutes=30), "on")]

    async def go() -> None:
        got = await make_house(ha).history(window("light.reading_lamp"))
        assert [s.id for s in got] == ["light.reading_lamp"]
        readings = [(r.at, r.state) for r in got[0].readings]
        assert readings[-2:] == [(T0 + timedelta(hours=1), "on"), (T0 + timedelta(hours=2), "off")]
        assert all(T0 <= at <= T0 + timedelta(hours=6) for at, _ in readings)
        assert all(isinstance(s, str) for _, s in readings)
        assert [at for at, _ in readings] == sorted(at for at, _ in readings)
    run(go())


def test_history_of_several_things_keeps_each_apart(ha: Ha) -> None:
    furnish(ha)
    ha.history["light.reading_lamp"] = [(T0 + timedelta(hours=1), "on")]
    ha.history["light.kitchen_strip"] = [(T0 + timedelta(hours=2), "off")]

    async def go() -> None:
        got = {s.id: [r.state for r in s.readings] for s in await make_house(ha).history(window("light.reading_lamp", "light.kitchen_strip"))}
        assert got == {"light.reading_lamp": ["on"], "light.kitchen_strip": ["off"]}
    run(go())


def test_history_of_a_thing_with_no_readings_has_none(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        got = await make_house(ha).history(window("light.kitchen_strip"))
        assert all(not s.readings for s in got)
    run(go())


def test_history_asks_for_the_window_it_was_given(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        await make_house(ha).history(window("light.reading_lamp", start=T0 + timedelta(hours=3), hours=2))
    run(go())
    (path,) = [(p, q) for _, p, q, _ in ha.requests if "/history/" in p]
    assert datetime.fromisoformat(path[0].rsplit("/", 1)[1].replace("Z", "+00:00")).astimezone(UTC) == T0 + timedelta(hours=3)
    assert datetime.fromisoformat(path[1]["end_time"].replace("Z", "+00:00")).astimezone(UTC) == T0 + timedelta(hours=5)
    assert path[1]["filter_entity_id"] == "light.reading_lamp"


def test_a_history_of_no_things_has_the_readings_of_none(ha: Ha) -> None:
    furnish(ha)
    ha.history["light.reading_lamp"] = [(T0 + timedelta(hours=1), "on")]

    async def go() -> None:
        try:
            got = await make_house(ha).history(window())
        except HouseRejected:
            return
        assert all(not s.readings for s in got)
    run(go())


def log(at: datetime, name: str, message: str, entity: str | None) -> dict[str, object]:
    row: dict[str, object] = {"when": at.isoformat(), "name": name, "message": message}
    if entity:
        row.update(entity_id=entity, domain=entity.split(".")[0])
    return row


def test_logbook_entries_in_the_window_with_their_ids_and_the_unattributed_as_none(ha: Ha) -> None:
    furnish(ha)
    ha.logbook = [log(T0 + timedelta(hours=1), "Reading lamp", "turned on", "light.reading_lamp"),
                  log(T0 + timedelta(hours=2), "Home Assistant", "started", None),
                  log(T0 + timedelta(hours=8), "Reading lamp", "turned off", "light.reading_lamp")]

    async def go() -> None:
        got = await make_house(ha).logbook(window())
        assert [(e.at, e.id, e.name, e.message) for e in got] == [
            (T0 + timedelta(hours=1), "light.reading_lamp", "Reading lamp", "turned on"),
            (T0 + timedelta(hours=2), None, "Home Assistant", "started")]
    run(go())


def test_logbook_of_named_things_holds_only_theirs(ha: Ha) -> None:
    furnish(ha)
    ha.logbook = [log(T0 + timedelta(hours=1), "Reading lamp", "turned on", "light.reading_lamp"),
                  log(T0 + timedelta(hours=2), "Kitchen strip", "turned off", "light.kitchen_strip")]

    async def go() -> None:
        got = await make_house(ha).logbook(window("light.kitchen_strip"))
        assert [e.id for e in got] == ["light.kitchen_strip"]
        both = await make_house(ha).logbook(window("light.kitchen_strip", "light.reading_lamp"))
        assert {e.id for e in both} == {"light.kitchen_strip", "light.reading_lamp"}
    run(go())


def test_actions_list_every_service_with_its_fields_and_whether_it_returns_data(ha: Ha) -> None:
    ha.service("calendar", "get_events", "Events in a range", {"start_date_time": "From", "duration": "For how long"}, response="only")
    ha.service("weather", "get_forecasts", "A forecast", response="optional")

    async def go() -> None:
        got = {a.name: a for a in await make_house(ha).actions()}
        assert set(got) == {"light.turn_on", "light.turn_off", "calendar.get_events", "weather.get_forecasts"}
        events = got["calendar.get_events"]
        assert events.description == "Events in a range"
        assert dict(events.fields) == {"start_date_time": "From", "duration": "For how long"}
        assert events.response == "only"
        assert got["weather.get_forecasts"].response == "optional"
        assert got["light.turn_on"].response == "none"
        assert dict(got["light.turn_on"].fields) == {"brightness_pct": "How bright"}
        assert dict(got["light.turn_off"].fields) == {}
    run(go())


def test_diagnostics_are_what_the_integration_reports_or_none(ha: Ha) -> None:
    furnish(ha)
    ha.diagnostics["entry_hue_bridge"] = {"home_assistant": {"version": "2026.10.4"}, "data": {"bridge": {"modelid": "BSB002-marker"}}}

    async def go() -> None:
        got = await make_house(ha).diagnostics("entry_hue_bridge")
        assert got is not None and "BSB002-marker" in json.dumps(got, default=str)
        assert await make_house(ha).diagnostics("entry_nothing") is None
    run(go())


def test_the_token_is_sent_as_a_bearer_on_every_request_and_on_the_socket(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        house = make_house(ha)
        await house.states()
        await house.actions()
    run(go())
    assert ha.requests and ha.connections >= 1


def test_what_the_house_holds_never_reaches_the_log(ha: Ha, caplog: pytest.LogCaptureFixture) -> None:
    furnish(ha)
    ha.add("sensor.secret_probe", "marker-state-4417", "Marker name 4417", registry=True, note="marker-attribute-4417")
    ha.history["sensor.secret_probe"] = [(T0 + timedelta(hours=1), "marker-state-4417")]
    ha.logbook = [log(T0 + timedelta(hours=1), "Marker name 4417", "marker-message-4417", "sensor.secret_probe")]
    caplog.set_level(logging.DEBUG)

    async def go() -> None:
        house = make_house(ha)
        await house.states()
        for kind in RECORD_KINDS:
            await house.records(kind)
        await house.history(window("sensor.secret_probe"))
        await house.logbook(window())
        await house.actions()
        with pytest.raises(HouseUnavailable):
            await make_house(ha, token="wrong-token-5521").states()
    run(go())
    ours = " ".join(f"{r.name} {r.getMessage()}" for r in caplog.records if r.name.startswith(("ashley", "httpx")))
    for secret in ("marker-state-4417", "Marker name 4417", "marker-attribute-4417", "marker-message-4417", TOKEN, "wrong-token-5521"):
        assert secret not in ours
