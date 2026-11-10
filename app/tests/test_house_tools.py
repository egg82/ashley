"""Her house tools over an in-memory House: the catalogue and its roster, `house_find` of every kind, `house_history`,
`house_do` and `house_ask` (names resolved in code, a name fitting several acts on none, the irreversible refused, reads
kept apart from changes), and the log line that carries counts and never a name."""

import asyncio
import json
from typing import Any

import pytest
from ashley.home_assistant import irreversible
from ashley.home_assistant.house import ActionInfo, Record
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_act import Rules
from ashley.tools.house_roster import devices
from ashley.tools.house_tools import HouseTools
from ashley.tools.tools import ToolsUnavailable
from house_double_support import MemoryHouse, ago, state
from ashley.home_assistant.house import LogEntry, Reading

RULES = Rules(("assist_satellite.announce",), ("script.find_person",), irreversible.load())
LOOK = house_look_config.load()


def house() -> MemoryHouse:
    h = MemoryHouse(things=[
        state("light.front_porch", "Front Porch", "off", "Porch", ("porch light",), ("veranda",)),
        state("light.porch_string", "Porch String", "on", "Porch", area_aliases=("veranda",)),
        state("light.hall", "Hall", "off", "Hall"),
        state("light.hall_strip", "Hall Strip", "off", "Hall"),
        state("input_boolean.hall", "Hall", "on", None, featured=False),
        state("sensor.rack", "Rack Temperature", "21", None, featured=False, device_class="temperature"),
        state("calendar.home", "Home", "off", None)])
    h.records_of = {
        "device": [Record("device", "d1", "Atom Echo Kitchen", {"area": "Kitchen", "model": "m5stack-atom",
                                                              "manufacturer": "Espressif", "integration": "esphome",
                                                              "integration_ids": ["e1"], "version": "2026.9.2"}),
                   Record("device", "d2", "Hue Bridge", {"area": "", "model": "bridge", "manufacturer": "Signify",
                                                         "integration": "hue", "disabled": False})],
        "area": [Record("area", "porch", "Porch", {"name": "Porch", "aliases": ["veranda"], "floor": ""})]}
    h.configs_of = {"automation": {"arrive": {"alias": "Arrival", "triggers": [{"trigger": "state"}] * 3}}, "script": {}}
    h.catalogue = [ActionInfo("light.turn_on", "Turn on", {"brightness_pct": "how bright"}, "none"),
                   ActionInfo("calendar.get_events", "Events", {"duration": "how long"}, "only"),
                   ActionInfo("homeassistant.restart", "Restart", {}, "none"),
                   ActionInfo("script.find_person", "Where", {}, "optional"),
                   ActionInfo("script.night", "Night", {}, "optional"),
                   ActionInfo("assist_satellite.announce", "Say", {}, "none")]
    h.returns = {"calendar.get_events": {"calendar.home": {"events": []}}}
    h.reports = {"e1": {"data": {"device_info": {"bluetooth_proxy_feature_flags": 0}}, "entry": {"title": "Echo"}}}
    h.readings = {"light.front_porch": [Reading(ago(90), "off"), Reading(ago(30), "on"), Reading(ago(5), "off")]}
    h.entries = [LogEntry(ago(3), "light.front_porch", "Front Porch", "turned off")]
    return h


def tools(h: MemoryHouse | None = None) -> HouseTools:
    return HouseTools(h or house(), RULES, LOOK, house_state_config.load(), "Guidance.")


def call(t: HouseTools, tool: str, **arguments: Any) -> ToolResult:
    return asyncio.run(t.call(ToolCall("c", tool, arguments)))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loaded: dict[str, Any] = json.loads(result.content)
    return loaded


def test_the_catalogue_offers_the_five_tools_and_lists_only_the_devices_the_household_lists() -> None:
    got = asyncio.run(tools().catalogue())
    assert [s.name for s in got.specs] == ["house_state", "house_find", "house_history", "house_ask", "house_do"]
    assert {s.name for s in got.specs if s.reads} == {"house_state", "house_find", "house_history", "house_ask"}
    assert got.instructions is not None and got.instructions.startswith("Guidance.")
    assert "Front Porch / porch light (light)" in got.instructions and "Rack Temperature" not in got.instructions
    assert "Devices in the house" in got.instructions and "Atom Echo Kitchen (m5stack-atom), Hue Bridge (bridge)" in got.instructions


def test_the_catalogue_is_kept_for_its_time_and_a_house_that_is_down_is_unavailable() -> None:
    h = house()
    t = tools(h)
    asyncio.run(t.catalogue())
    reads = h.reads
    asyncio.run(t.catalogue())
    assert h.reads == reads
    h.down = True
    with pytest.raises(ToolsUnavailable):
        asyncio.run(tools(h).catalogue())


def test_the_line_of_devices_leaves_out_what_has_no_maker_or_model_and_says_how_many_more_do_not_fit() -> None:
    records = tuple(Record("device", f"d{i}", f"Gadget {i:02d}", {"model": "x"}) for i in range(40))
    quiet = (Record("device", "s", "Sun", {}), Record("device", "off", "Old", {"model": "y", "disabled": True}))
    line = devices(records + quiet, 120)
    assert line.startswith("Gadget 00 (x), Gadget 01 (x)") and "Sun" not in line and "Old" not in line
    assert len(line.split(", and ")[0]) <= 120 and line.endswith(f", and {40 - line.count('Gadget')} more")
    assert devices(quiet, 120) == "" and devices((), 120) == ""


def test_find_narrows_records_by_words_across_name_maker_model_and_integration() -> None:
    got = body(call(tools(), "house_find", kind="device", name="atom echo"))
    assert [r["id"] for r in got["records"]] == ["d1"] and got["complete"] is True and got["total"] == 1
    assert got["records"][0]["integration_ids"] == ["e1"] and got["records"][0]["version"] == "2026.9.2"
    assert [r["id"] for r in body(call(tools(), "house_find", kind="device", name="signify"))["records"]] == ["d2"]
    assert [r["id"] for r in body(call(tools(), "house_find", kind="device", domain="esphome"))["records"]] == ["d1"]
    assert body(call(tools(), "house_find", kind="device", name="nothing like it"))["total"] == 0


def test_a_listing_too_large_is_names_then_counts_and_says_how_to_narrow() -> None:
    h = house()
    h.records_of["entity"] = [Record("entity", f"sensor.s{i}", f"Sensor {i}", {"area": "", "domain": "sensor", "note": "x" * 80})
                              for i in range(120)]
    got = body(call(tools(h), "house_find", kind="entity"))
    assert got["complete"] is True and got["narrow_by"] == ["id"] and len(got["records"]) == 120
    assert set(got["records"][0]) == {"id", "name"}
    h.records_of["entity"] = [Record("entity", f"sensor.s{i}", f"Sensor {i}", {}) for i in range(900)]
    counted = body(call(tools(h), "house_find", kind="entity"))
    assert counted["complete"] is False and "records" not in counted and counted["total"] == 900


def test_find_gives_a_config_by_id_and_lists_configs_by_name() -> None:
    t = tools()
    assert body(call(t, "house_find", kind="automation"))["items"] == [{"id": "arrive", "name": "Arrival"}]
    assert body(call(t, "house_find", kind="automation", id="arrive"))["config"]["alias"] == "Arrival"
    assert body(call(t, "house_find", kind="automation", id="gone"))["found"] is False
    assert body(call(t, "house_find", kind="automation", name="zzz"))["items"] == []


def test_find_actions_lists_and_gives_one_actions_fields() -> None:
    t = tools()
    assert [a["id"] for a in body(call(t, "house_find", kind="action", domain="light"))["actions"]] == ["light.turn_on"]
    one = body(call(t, "house_find", kind="action", id="light.turn_on"))
    assert one["fields"] == {"brightness_pct": "how bright"} and one["returns"] == "none"


def test_diagnostics_are_read_whole_or_drilled_by_path_and_an_unreporting_integration_says_so() -> None:
    t = tools()
    assert body(call(t, "house_find", kind="diagnostics", id="e1"))["report"]["entry"] == {"title": "Echo"}
    drilled = body(call(t, "house_find", kind="diagnostics", id="e1", path="data.device_info"))
    assert drilled["report"] == {"bluetooth_proxy_feature_flags": 0} and drilled["path"] == "data.device_info"
    assert call(t, "house_find", kind="diagnostics", id="e1", path="data.nope").is_error
    assert body(call(t, "house_find", kind="diagnostics", id="zz"))["reported"] is False
    assert call(t, "house_find", kind="diagnostics").is_error


def test_a_large_report_is_outlined_by_key_with_sizes_and_never_cut() -> None:
    h = house()
    h.reports["big"] = {"a": {"k": "x" * 9000}, "b": [1, 2, 3]}
    got = body(call(tools(h), "house_find", kind="diagnostics", id="big"))
    assert got["complete"] is False and got["narrow_by"] == ["path"]
    assert got["report"] == {"a": "object of 1", "b": "list of 3"}


@pytest.mark.parametrize("arguments", [{"kind": "toaster"}, {}, {"kind": "device", "colour": "red"}, {"kind": 3}])
def test_find_refuses_arguments_off_its_schema(arguments: dict[str, Any]) -> None:
    assert call(tools(), "house_find", **arguments).is_error


def test_history_gives_changes_as_minutes_ago_and_needs_the_things_named() -> None:
    t = tools()
    got = body(call(t, "house_history", ids=["light.front_porch"], hours=2))
    (thing,) = got["things"]
    assert thing["readings"] == [{"ago_min": 90, "state": "off"}, {"ago_min": 30, "state": "on"}, {"ago_min": 5, "state": "off"}]
    assert got["complete"] is True
    assert body(call(t, "house_history", name="porch light"))["things"][0]["id"] == "light.front_porch"
    assert call(t, "house_history").is_error
    assert call(t, "house_history", name="sauna").is_error
    assert call(t, "house_history", name="porch").is_error


def test_a_long_history_shows_the_latest_changes_and_says_so() -> None:
    h = house()
    h.readings["light.front_porch"] = [Reading(ago(500 - i), "on" if i % 2 else "off") for i in range(100)]
    got = body(call(tools(h), "house_history", ids=["light.front_porch"]))
    assert got["complete"] is False and len(got["things"][0]["readings"]) == LOOK.readings_per_thing
    assert got["things"][0]["changes"] == 100


def test_the_logbook_needs_no_names_and_is_the_whole_house() -> None:
    got = body(call(tools(), "house_history", kind="logbook", hours=1))
    assert got["entries"] == [{"ago_min": 3, "name": "Front Porch", "what": "turned off"}] and got["complete"] is True
    assert call(tools(), "house_history", kind="diary").is_error


def test_do_resolves_a_name_through_its_alias_and_performs_the_action_on_that_thing() -> None:
    h = house()
    got = body(call(tools(h), "house_do", action="light.turn_on", name="porch light", data={"brightness_pct": 30}))
    assert got["done"] is True and [c["id"] for c in got["changed"]] == ["light.front_porch"]
    assert h.done == [("perform", "action", "light.turn_on", ("light.front_porch",), {"brightness_pct": 30})]


def test_data_may_be_given_as_json_text_which_is_what_the_schema_offers() -> None:
    h = house()
    body(call(tools(h), "house_do", action="light.turn_on", name="porch light", data='{"brightness_pct": 30}'))
    assert h.done[0][4] == {"brightness_pct": 30}
    for bad in ('{"x": ', "[1]", "3"):
        assert call(tools(h), "house_do", action="light.turn_on", name="porch light", data=bad).is_error
    spec = {s.name: s for s in asyncio.run(tools(h).catalogue()).specs}["house_do"]
    properties: Any = spec.parameters["properties"]
    assert properties["data"]["type"] == "string"


def test_do_by_area_acts_on_everything_of_the_actions_domain_in_it() -> None:
    h = house()
    body(call(tools(h), "house_do", action="light.turn_on", area="veranda"))
    assert h.done[0][3] == ("light.front_porch", "light.porch_string")


def test_a_name_fitting_several_things_acts_on_none_and_says_which() -> None:
    h = house()
    got = call(tools(h), "house_do", action="light.turn_on", name="strip")
    assert not got.is_error and h.done[0][3] == ("light.hall_strip",)
    h.done.clear()
    ambiguous = call(tools(h), "house_do", action="light.turn_on", name="porch")
    assert ambiguous.is_error and "Front Porch" in ambiguous.content and "Porch String" in ambiguous.content
    assert h.done == []


def test_an_exact_name_beats_a_longer_one_and_the_listed_beats_the_unlisted() -> None:
    h = house()
    body(call(tools(h), "house_do", action="light.turn_on", name="hall"))
    assert h.done[0][3] == ("light.hall",)
    h.done.clear()
    body(call(tools(h), "house_do", action="homeassistant.turn_on", name="hall"))
    assert h.done[0][3] == ("light.hall",), "the light is listed for her, the helper of the same name is not"


def test_a_name_no_thing_fits_is_final_and_nothing_is_done() -> None:
    h = house()
    got = call(tools(h), "house_do", action="light.turn_on", name="sauna")
    assert got.is_error and "no such thing" in got.content and h.done == []
    assert call(tools(h), "house_do", action="light.turn_on", ids=["light.nope"]).is_error and h.done == []


def test_an_irreversible_action_is_not_run_and_an_excluded_one_is_unknown() -> None:
    h = house()
    refused = call(tools(h), "house_do", action="homeassistant.restart")
    assert refused.is_error and "OK" in refused.content and h.done == []
    unknown = call(tools(h), "house_do", action="assist_satellite.announce", name="hall")
    assert unknown.is_error and "no action named" in unknown.content and h.done == []
    assert call(tools(h), "house_do", action="nodots").is_error


def test_ask_runs_only_actions_that_only_read_and_refuses_the_rest() -> None:
    h = house()
    t = tools(h)
    got = body(call(t, "house_ask", action="calendar.get_events", name="home", data={"duration": {"hours": 1}}))
    assert got["response"] == {"calendar.home": {"events": []}}
    assert call(t, "house_ask", action="script.find_person").is_error is False, "named under reads"
    changing = call(t, "house_ask", action="light.turn_on", name="porch light")
    assert changing.is_error and "house_do" in changing.content
    assert [d[2] for d in h.done] == ["calendar.get_events", "script.find_person"]


def test_a_house_that_refuses_is_a_result_and_one_that_is_down_is_unavailable() -> None:
    h = house()
    h.refuse = "bad brightness"
    refused = call(tools(h), "house_do", action="light.turn_on", name="porch light")
    assert refused.is_error and "bad brightness" in refused.content
    h.refuse, h.down = None, True
    assert call(tools(h), "house_do", action="light.turn_on", name="porch light").content == "the house did not answer"


def test_an_unknown_tool_is_an_error_result() -> None:
    assert call(tools(), "house_nothing").is_error


def test_a_call_logs_the_tool_outcome_and_counts_but_no_name_id_or_state(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="ashley.tools"):
        call(tools(), "house_do", action="light.turn_on", name="porch light")
        call(tools(), "house_find", kind="device", name="atom echo")
    lines = [getattr(r, "fields") for r in caplog.records if r.getMessage() == "tools.call"]
    assert [(f["tool"], f["outcome"]) for f in lines] == [("house_do", "ok"), ("house_find", "ok")]
    assert lines[0]["named"] == 1 and lines[1]["matched"] == 1 and lines[1]["kind"] == "device"
    assert not any(w in str(lines) for w in ("porch", "Porch", "atom", "Atom", "light.front"))
