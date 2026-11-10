"""`house_state` from its described contract: one tool with optional `area`, `domain` and `name`; no arguments answers
every area, an area every domain in it, anything else the entities with their states; every list is whole, an answer
past the cap says so in `complete` and `narrow_by`; `matched` 0 is final; read from the house per call."""

import asyncio
from dataclasses import replace

import pytest

from ashley.inference.model import ToolCall
from ashley.tools import house_state_config
from ashley.tools.house_state import HouseStateTools
from ashley.tools.house_state_config import HouseStateConfig
from house_double_support import MemoryHouse
from house_support import ask, device, house_of, read, tools

CONFIG = house_state_config.load()
HOUSE = [
    device("Kitchen Light, Big Light", "light", "on", "Kitchen", brightness=180),
    device("Pantry Light", "light", "off", "Kitchen"),
    device("Sink Light", "light", "off", "Kitchen"),
    device("Thermostat", "climate", "heat", "Kitchen", current_temperature=70, temperature=68),
    device("Porch Light", "light", "off", "Front Yard, Porch"),
    device("Front Door", "binary_sensor", "off", "Front Yard, Porch", device_class="door"),
    device("Alana", "person", "home"),
    device("Shopping List", "todo", "3"),
]


def test_no_arguments_answers_every_area_with_a_summary_including_the_devices_in_none() -> None:
    body = read(tools(HOUSE, CONFIG)[0])
    assert body["level"] == "house" and body["complete"] is True
    areas = {a["area"]: a["summary"] for a in body["areas"]}
    assert set(areas) == {"Kitchen", "Front Yard", "(no area)"}
    assert "light 3 (off 2, on 1)" in areas["Kitchen"] and "Thermostat heat" in areas["Kitchen"]
    assert "70" in areas["Kitchen"]
    assert "Alana home" in areas["(no area)"] and "Shopping List 3" in areas["(no area)"]


def test_an_area_answers_every_domain_in_it_by_name_or_alias_in_any_case() -> None:
    tool = tools(HOUSE, CONFIG)[0]
    body = read(tool, area="kitchen")
    assert body["level"] == "area" and body["area"] == "Kitchen" and body["complete"] is True
    assert [d["domain"] for d in body["domains"]] == ["climate", "light"]
    assert read(tool, area="porch")["area"] == "Front Yard"
    assert [d["domain"] for d in read(tool, area="(no area)")["domains"]] == ["person", "todo"]


def test_area_and_domain_answer_the_entities_with_their_states_and_attributes() -> None:
    body = read(tools(HOUSE, CONFIG)[0], area="Kitchen", domain="light")
    assert body["level"] == "entities" and body["matched"] == 3 and body["complete"] is True
    lights = {e["names"]: e for e in body["entities"]}
    assert set(lights) == {"Kitchen Light, Big Light", "Pantry Light", "Sink Light"}
    assert lights["Kitchen Light, Big Light"]["state"] == "on"
    assert lights["Kitchen Light, Big Light"]["attributes"] == {"brightness": 180}


@pytest.mark.parametrize(("name", "expected"), [
    ("porch light", {"Porch Light"}),
    ("big light", {"Kitchen Light, Big Light"}),          # an alias
    ("PANTRY", {"Pantry Light"}),
    ("kitchen lights", {"Kitchen Light, Big Light", "Pantry Light", "Sink Light"}),   # area words, a plural
    ("door", {"Front Door"}),                             # its device_class
    ("temp", set[str]()),                                 # no word begins "temp" here
    ("thermo", {"Thermostat"}),
])
def test_a_name_matches_on_the_entities_fields_with_every_word(name: str, expected: set[str]) -> None:
    body = read(tools(HOUSE, CONFIG)[0], name=name)
    assert {e["names"] for e in body.get("entities", [])} == expected


def test_a_name_matching_nothing_is_final_says_which_words_matched_nothing_and_shows_the_whole_house() -> None:
    body = read(tools(HOUSE, CONFIG)[0], name="garage door")
    house = body.pop("house")
    assert body == {"level": "entities", "matched": 0, "complete": True, "unmatched_words": ["garage"]}
    assert house == read(tools(HOUSE, CONFIG)[0])
    assert read(tools(HOUSE, CONFIG)[0], name="porch thermostat")["matched"] == 0


def test_an_unknown_area_or_domain_matches_nothing_and_names_what_there_is() -> None:
    tool = tools(HOUSE, CONFIG)[0]
    body = read(tool, area="Garage")
    assert body["matched"] == 0 and body["known_areas"] == ["Front Yard", "Kitchen", "(no area)"]
    body = read(tool, domain="cover")
    assert body["matched"] == 0 and "light" in body["known_domains"]


def test_blank_arguments_are_left_out_and_bad_ones_are_refused_before_reading_the_house() -> None:
    tool, house = tools(HOUSE, CONFIG)
    assert read(tool, area=" ", name="")["level"] == "house"
    reads = house.reads
    for bad in ({"area": 3}, {"room": "Kitchen"}, {"all": "yes"}):
        result = asyncio.run(tool.call(ToolCall("c", "house_state", bad)))
        assert result.is_error
    assert house.reads == reads


def test_every_call_reads_the_house_afresh() -> None:
    tool, house = tools(HOUSE, CONFIG)
    assert read(tool, name="kitchen light")["entities"][0]["state"] == "on"
    house.things[:] = house_of([device("Kitchen Light", "light", "off", "Kitchen")]).things
    assert read(tool, area="Kitchen", domain="light")["entities"][0]["state"] == "off"
    assert house.reads == 2


def test_the_house_being_down_is_an_error() -> None:
    house = house_of(HOUSE)
    house.down = True
    result = ask(HouseStateTools(house, CONFIG))
    assert result.is_error and result.content == "the house did not answer"


def test_things_the_household_does_not_list_are_left_out_unless_all_is_asked_for() -> None:
    unlisted = replace(house_of([device("Guest Mode", "input_boolean", "on")]).things[0], featured=False)
    house = MemoryHouse(things=[*house_of(HOUSE).things, unlisted])
    tool = HouseStateTools(house, CONFIG)
    assert "Guest Mode" not in str(read(tool))
    assert "Guest Mode" in str(read(tool, all=True, name="guest mode"))


def test_a_call_logs_its_level_counts_and_cap_but_no_name_state_or_argument(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="ashley.tools"):
        read(tools(HOUSE, CONFIG)[0], area="Kitchen")
    lines = [r for r in caplog.records if r.getMessage() == "tools.call"]
    assert len(lines) == 1
    fields: dict[str, object] = getattr(lines[0], "fields")
    assert fields["tool"] == "house_state" and fields["outcome"] == "ok" and fields["level"] == "area"
    assert fields["children"] == 2 and fields["capped"] is False and "duration_ms" in fields
    assert not any(word in str(fields) for word in ("Kitchen", "Light", "heat", "Thermostat"))


def test_the_shipped_config_parses_and_a_bad_one_is_refused() -> None:
    assert CONFIG.max_chars > 0
    good: dict[str, object] = {"max_chars": 10, "list_at_most": 1, "tally_at_most": 1, "summary_attributes": [],
                               "outside_domains": []}
    assert house_state_config.parse(good) == HouseStateConfig(10, 1, 1, (), ())
    bads: list[object] = [{**good, "max_chars": 0}, {**good, "extra": 1}, {**good, "summary_attributes": [""]},
                         {k: v for k, v in good.items() if k != "list_at_most"}, []]
    for bad in bads:
        with pytest.raises(ValueError):
            house_state_config.parse(bad)


