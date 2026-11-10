"""HaHouse's writes against a stand-in Home Assistant: actions, automation, script and helper configs, area, floor and
label records, entity and device fields, and removals (`house.House` and `ha_house.HaHouse`)."""

import logging
from typing import Any

import pytest
from ashley.home_assistant.house import HouseRejected, HouseUnavailable
from contract.conversations_support import run
from hag_state_support import TOKEN, Ha
from hag_support import furnish, make_house

AUTOMATION: dict[str, Any] = {"alias": "Porch at dusk", "description": "", "mode": "single",
                              "triggers": [{"trigger": "sun", "event": "sunset"}],
                              "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.kitchen_strip"}}]}


def test_an_action_runs_on_the_things_named_and_reports_what_changed(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        done = await make_house(ha).perform("light.turn_on", ("light.reading_lamp",), {"brightness_pct": 40})
        assert [(s.id, s.state) for s in done.changed] == [("light.reading_lamp", "on")]
        assert done.response is None
    run(go())
    (method, path, _, body) = [r for r in ha.requests if r[1].startswith("/api/services/")][0]
    assert (method, path) == ("POST", "/api/services/light/turn_on")
    asked = [body["entity_id"]] if isinstance(body["entity_id"], str) else list(body["entity_id"])
    assert body["brightness_pct"] == 40 and asked == ["light.reading_lamp"]
    assert ha.states["light.reading_lamp"]["state"] == "on"


def test_an_action_on_several_things_changes_each(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        done = await make_house(ha).perform("light.turn_off", ("light.reading_lamp", "light.kitchen_strip"), {})
        assert {(s.id, s.state) for s in done.changed} == {("light.reading_lamp", "off"), ("light.kitchen_strip", "off")}
    run(go())


def test_an_action_on_nothing_named_sends_no_entity_id(ha: Ha) -> None:
    furnish(ha)
    ha.service("script", "turn_on_all", "Start", then=lambda _h, _d: [])

    async def go() -> None:
        done = await make_house(ha).perform("script.turn_on_all", (), {"note": "x"})
        assert done.changed == ()
    run(go())
    body = [r[3] for r in ha.requests if r[1] == "/api/services/script/turn_on_all"][0]
    assert "entity_id" not in body and body["note"] == "x"


def test_an_action_that_only_returns_data_is_asked_for_it_and_returns_it(ha: Ha) -> None:
    furnish(ha)
    ha.service("calendar", "get_events", "Events", {"duration": "How long"}, response="only",
               returns={"calendar.family": {"events": [{"summary": "Dentist"}]}})

    async def go() -> None:
        done = await make_house(ha).perform("calendar.get_events", ("calendar.family",), {"duration": {"hours": 4}})
        assert done.changed == ()
        assert done.response == {"calendar.family": {"events": [{"summary": "Dentist"}]}}
    run(go())


def test_an_action_that_may_return_data_runs_and_a_plain_one_is_not_asked_for_any(ha: Ha) -> None:
    furnish(ha)
    ha.service("weather", "get_forecasts", "Forecast", response="optional", returns={"weather.home": {"forecast": []}})

    async def go() -> None:
        house = make_house(ha)
        await house.perform("weather.get_forecasts", ("weather.home",), {})
        plain = await house.perform("light.turn_on", ("light.reading_lamp",), {})
        assert plain.response is None
    run(go())


def test_an_action_the_house_does_not_have_or_refuses_is_rejected_and_changes_nothing(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseRejected):
            await make_house(ha).perform("light.no_such_action", ("light.reading_lamp",), {})
    run(go())
    assert ha.states["light.reading_lamp"]["state"] == "off"


def test_an_action_the_house_fails_on_is_unavailable(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        ha.status = 503
        with pytest.raises(HouseUnavailable):
            await make_house(ha).perform("light.turn_on", ("light.reading_lamp",), {})
        ha.status = None
        ha.garbage = True
        with pytest.raises(HouseUnavailable):
            await make_house(ha).perform("light.turn_on", ("light.reading_lamp",), {})
    run(go())


def test_an_automation_is_written_listed_read_back_replaced_and_deleted(ha: Ha) -> None:
    async def go() -> None:
        house = make_house(ha)
        assert await house.configs("automation") == ()
        assert await house.config("automation", "porch") is None
        assert await house.write_config("automation", "porch", AUTOMATION) == "porch"
        got = await house.config("automation", "porch")
        assert got is not None and got["alias"] == "Porch at dusk" and got["triggers"] == AUTOMATION["triggers"]
        assert [(c.id, c.name) for c in await house.configs("automation")] == [("porch", "Porch at dusk")]
        assert await house.write_config("automation", "porch", {**AUTOMATION, "alias": "Porch at sunset"}) == "porch"
        again = await house.config("automation", "porch")
        assert again is not None and again["alias"] == "Porch at sunset"
        assert len(await house.configs("automation")) == 1
        assert await house.delete_config("automation", "porch") is True
        assert await house.delete_config("automation", "porch") is False
        assert await house.config("automation", "porch") is None
    run(go())


def test_scripts_are_their_own_kind(ha: Ha) -> None:
    async def go() -> None:
        house = make_house(ha)
        await house.write_config("script", "goodnight", {**AUTOMATION, "alias": "Goodnight"})
        await house.write_config("automation", "porch", AUTOMATION)
        assert [c.id for c in await house.configs("script")] == ["goodnight"]
        assert [c.id for c in await house.configs("automation")] == ["porch"]
        assert await house.config("script", "porch") is None
        assert await house.delete_config("script", "porch") is False
    run(go())


def test_a_new_automation_with_no_id_never_replaces_one_that_exists(ha: Ha) -> None:
    ha.put_config("automation", "porch_at_dusk", AUTOMATION)

    async def go() -> None:
        house = make_house(ha)
        new_id = await house.write_config("automation", None, {**AUTOMATION, "actions": []})
        assert new_id and new_id != "porch_at_dusk"
        old = await house.config("automation", "porch_at_dusk")
        assert old is not None and old["actions"] == AUTOMATION["actions"]
        assert {c.id for c in await house.configs("automation")} == {"porch_at_dusk", new_id}
    run(go())


def test_a_config_the_house_rejects_raises_rejected_with_its_reason_and_writes_nothing(ha: Ha) -> None:
    async def go() -> None:
        with pytest.raises(HouseRejected) as raised:
            await make_house(ha).write_config("automation", "bad", {"description": "no alias"})
        assert "alias" in raised.value.message
    run(go())
    assert ha.configs["automation"] == {}


def test_a_config_write_the_house_fails_on_is_unavailable(ha: Ha) -> None:
    async def go() -> None:
        ha.status = 500
        with pytest.raises(HouseUnavailable):
            await make_house(ha).write_config("automation", "porch", AUTOMATION)
        with pytest.raises(HouseUnavailable):
            await make_house(ha).config("automation", "porch")
    run(go())


def test_a_helper_is_created_listed_read_changed_and_deleted_by_its_typed_id(ha: Ha) -> None:
    async def go() -> None:
        house = make_house(ha)
        made = await house.write_config("helper", None, {"type": "input_boolean", "name": "Guest mode"})
        assert made == "input_boolean:guest_mode"
        assert [(c.id, c.name) for c in await house.configs("helper")] == [("input_boolean:guest_mode", "Guest mode")]
        got = await house.config("helper", made)
        assert got is not None and got["type"] == "input_boolean" and got["name"] == "Guest mode"
        assert await house.write_config("helper", made, {"type": "input_boolean", "name": "Guests over"}) == made
        changed = await house.config("helper", made)
        assert changed is not None and changed["name"] == "Guests over"
        assert len(await house.configs("helper")) == 1
        assert await house.delete_config("helper", made) is True
        assert await house.delete_config("helper", made) is False
        assert await house.config("helper", made) is None
        assert await house.configs("helper") == ()
    run(go())


def test_helpers_of_different_types_are_listed_together_with_their_own_ids(ha: Ha) -> None:
    async def go() -> None:
        house = make_house(ha)
        a = await house.write_config("helper", None, {"type": "input_number", "name": "Target", "min": 10, "max": 30, "step": 1})
        b = await house.write_config("helper", None, {"type": "counter", "name": "Laps"})
        assert a.startswith("input_number:") and b.startswith("counter:")
        assert {c.id for c in await house.configs("helper")} == {a, b}
        number = await house.config("helper", a)
        assert number is not None and number["max"] == 30
    run(go())


def test_nothing_a_change_carries_reaches_the_log_or_an_error(ha: Ha, caplog: pytest.LogCaptureFixture) -> None:
    furnish(ha)
    marker: dict[str, Any] = {"alias": "marker-alias-6203", "triggers": [], "actions": [], "description": "marker-description-6203"}
    caplog.set_level(logging.DEBUG)

    async def go() -> None:
        house = make_house(ha)
        await house.write_config("automation", "m", marker)
        await house.create_record("area", {"name": "marker-area-6203"})
        await house.perform("light.turn_on", ("light.reading_lamp",), {"note": "marker-data-6203"})
        with pytest.raises(HouseRejected):
            await house.write_config("automation", "n", {"description": "marker-description-6203"})
        ha.status = 500
        with pytest.raises(HouseUnavailable) as raised:
            await house.write_config("automation", "o", marker)
        for secret in ("marker-alias-6203", "marker-description-6203", TOKEN):
            assert secret not in str(raised.value)
    run(go())
    ours = " ".join(f"{r.name} {r.getMessage()}" for r in caplog.records if r.name.startswith(("ashley", "httpx")))
    for secret in ("marker-alias-6203", "marker-description-6203", "marker-area-6203", "marker-data-6203", TOKEN):
        assert secret not in ours


def test_an_action_the_house_refuses_is_asked_once_and_not_retried_for_data(ha: Ha) -> None:
    furnish(ha)
    ha.service("weather", "get_forecasts", "Forecast", response="optional", returns={"weather.home": {}})
    ha.reject_calls = True

    async def go() -> None:
        for action in ("weather.get_forecasts", "light.turn_on"):
            with pytest.raises(HouseRejected) as raised:
                await make_house(ha).perform(action, ("light.reading_lamp",), {})
            assert "refused-marker" in raised.value.message
    run(go())
    assert [(m, p) for m, p, _, _ in ha.requests if p.startswith("/api/services/") and p != "/api/services"].count(
        ("POST", "/api/services/weather/get_forecasts")) == 1
    assert not any(q for _, p, q, _ in ha.requests if p.startswith("/api/services/") and "return_response" in q)
