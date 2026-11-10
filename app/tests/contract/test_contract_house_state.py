"""Blind contract tests for `HouseStateTools` (docstrings, the tool's own description, `decisions.md` "She reads the
house's state through `house_state`", `house_state.json`'s tunables). Each test names its contract line (HS-n, Tools-1)
in `notes/blind-house-move.txt`."""

import json
from dataclasses import replace
from typing import Any

import pytest
from ashley import logs
from ashley.tools.house_state import SPEC, HouseStateTools
from ashley.tools.house_state_config import HouseStateConfig, load
from conversations_support import events
from house_support import Device, ask, device, house_of, read, tools

CONFIG = load()


def house() -> list[Device]:
    return [
        device("Kitchen Light, Counter Lamp", "light", "on", "Kitchen"),
        device("Kitchen Fan", "fan", "off", "Kitchen"),
        device("Hall Light", "light", "off", "Hall"),
        device("Front Door", "lock", "locked", "Hall"),
        device("Porch Light", "light", "on"),
        device("Thermostat", "climate", "heat", "Hall", current_temperature=21),
    ]


def big(n: int) -> list[Device]:
    return [device(f"Lamp {i:03d}", "light", "on" if i % 2 else "off", "Den") for i in range(n)]


def entities(body: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = body.get("entities", [])
    return found


def areas_anywhere(body: object) -> set[str]:
    """Every area name an answer shows, wherever in it (the contract says the whole house is shown beside a miss)."""
    found: set[str] = set()
    loose: Any = body
    if isinstance(body, dict):
        if "area" in loose and len(loose) <= 3:
            found.add(str(loose["area"]))
        for v in loose.values():
            found |= areas_anywhere(v)
    elif isinstance(body, list):
        for v in loose:
            found |= areas_anywhere(v)
    return found


# HS-1: the catalogue ------------------------------------------------------------------------------------------------

def test_the_tool_takes_area_domain_name_and_all() -> None:
    props: Any = SPEC.parameters["properties"]
    assert set(props) == {"area", "domain", "name", "all"} and SPEC.reads is True


# Tools-1 / HS-6: errors are results ---------------------------------------------------------------------------------

def test_a_source_that_is_down_at_call_time_is_an_error_result() -> None:
    down = house_of(house())
    down.down = True
    assert ask(HouseStateTools(down, CONFIG)).is_error


@pytest.mark.parametrize("arguments", [{"area": 3}, {"domain": ["light"]}, {"name": None}, {"nonsense": "x"}])
def test_arguments_off_the_schema_never_raise(arguments: dict[str, object]) -> None:
    t, _ = tools(house(), CONFIG)
    result = ask(t, **arguments)
    assert result.call_id == "c1"
    json.loads(result.content) if not result.is_error else None


# HS-3: read afresh ------------------------------------------------------------------------

def test_each_call_reads_the_house_once() -> None:
    t, house_ = tools(house(), CONFIG)
    read(t)
    read(t, area="Kitchen")
    read(t, domain="light")
    assert house_.reads == 3


def test_a_change_in_the_house_shows_on_the_next_call() -> None:
    t, house_ = tools(house(), CONFIG)
    before = read(t, name="porch light")
    house_.things[:] = house_of([device("Porch Light", "light", "off")] + house()[:-2]).things
    after = read(t, name="porch light")
    assert [e["state"] for e in entities(before)] == ["on"]
    assert [e["state"] for e in entities(after)] == ["off"]


# HS-2: narrowing like a map -----------------------------------------------------------------------------------------

def test_no_arguments_gives_every_area_summarised() -> None:
    body = read(tools(house(), CONFIG)[0])
    assert {a["area"] for a in body["areas"]} >= {"Kitchen", "Hall"}
    assert "entities" not in body


def test_an_area_gives_every_domain_in_it() -> None:
    body = read(tools(house(), CONFIG)[0], area="Kitchen")
    assert {d["domain"] for d in body["domains"]} == {"light", "fan"}


def test_a_domain_gives_the_entities_with_their_states() -> None:
    body = read(tools(house(), CONFIG)[0], domain="light")
    got = {(e["domain"], e["state"]) for e in entities(body)}
    assert got == {("light", "on"), ("light", "off")}
    assert len(entities(body)) == 3


def test_an_area_and_a_domain_give_just_those_entities() -> None:
    body = read(tools(house(), CONFIG)[0], area="Hall", domain="light")
    assert [(e["area"], e["state"]) for e in entities(body)] == [("Hall", "off")]


def test_a_name_gives_the_entities_it_matches() -> None:
    body = read(tools(house(), CONFIG)[0], name="front door")
    assert [e["state"] for e in entities(body)] == ["locked"]


def test_an_alias_matches_like_a_name() -> None:
    body = read(tools(house(), CONFIG)[0], name="counter lamp")
    assert [e["state"] for e in entities(body)] == ["on"]


def test_the_area_of_a_name_match_is_one_of_its_matchable_fields() -> None:
    body = read(tools(house(), CONFIG)[0], name="kitchen")
    assert {e["domain"] for e in entities(body)} == {"light", "fan"}


# HS-5: every word of a name must match; matched 0 is final -------------------------------------------------------------

def test_every_word_of_a_name_must_match() -> None:
    body = read(tools(house(), CONFIG)[0], name="kitchen lock")
    assert body["matched"] == 0
    assert entities(body) == []


def test_a_name_matching_nothing_says_matched_zero_and_shows_the_house() -> None:
    body = read(tools(house(), CONFIG)[0], name="submarine")
    assert body["matched"] == 0
    assert entities(body) == []
    assert areas_anywhere(body) >= {"Kitchen", "Hall"}


def test_a_name_that_matches_counts_what_it_matched() -> None:
    assert read(tools(house(), CONFIG)[0], name="light")["matched"] == 3


# HS-4: complete, or says it is not; never a cut list ----------------------------------------------------------------------

def test_a_small_answer_lists_every_child_and_is_complete() -> None:
    body = read(tools(house(), CONFIG)[0], domain="light")
    assert body.get("complete", True) is True
    assert "narrow_by" not in body


def test_a_big_answer_is_never_a_cut_list() -> None:
    t, _ = tools(big(400), CONFIG)
    body = read(t, domain="light")
    listed = entities(body) if "entities" in body else []
    if body.get("complete", True) is True:
        assert len(listed) == 400
    else:
        assert body["narrow_by"]
        assert len(listed) == 400 or all("state" not in e for e in listed)


def test_a_big_answer_stays_within_the_cap() -> None:
    tiny = replace(CONFIG, max_chars=600)
    result = ask(tools(big(400), tiny)[0], domain="light")
    assert not result.is_error and len(result.content) <= tiny.max_chars


def test_an_answer_over_the_cap_says_it_is_not_complete_and_how_to_narrow() -> None:
    tiny = replace(CONFIG, max_chars=600)
    body = read(tools(big(400), tiny)[0], domain="light")
    assert body["complete"] is False
    assert body["narrow_by"]


def test_what_was_left_out_of_a_big_answer_is_reachable_by_narrowing() -> None:
    tiny = replace(CONFIG, max_chars=600)
    t, _ = tools(big(60), tiny)
    body = read(t, domain="light")
    assert body["complete"] is False
    one = read(t, name="lamp 017")
    assert [e["state"] for e in entities(one)] == ["on"]


def test_the_cap_is_the_configured_one() -> None:
    roomy = replace(CONFIG, max_chars=200000)
    body = read(tools(big(400), roomy)[0], domain="light")
    assert body.get("complete", True) is True and len(entities(body)) == 400


# HS-7: the tools.call line ----------------------------------------------------------------------------------------------

def test_a_call_logs_its_outcome_and_duration_and_nothing_it_was_asked_or_told(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    read(tools([device("Secret Lamp Zed", "light", "on", "Hidden Attic")], CONFIG)[0], area="Hidden Attic", name="zed")
    out = capsys.readouterr().out
    (line,) = events(out, "tools.call")
    assert "duration_ms" in line and "ok" in line.values()
    for leaked in ("Secret", "Zed", "zed", "Hidden", "Attic"):
        assert leaked not in out


def test_a_failed_call_logs_a_non_ok_outcome(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    down = house_of(house())
    down.down = True
    ask(HouseStateTools(down, CONFIG))
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert "ok" not in line.values()


def test_the_config_loads_with_counts_that_are_positive() -> None:
    assert isinstance(CONFIG, HouseStateConfig)
    assert min(CONFIG.max_chars, CONFIG.list_at_most, CONFIG.tally_at_most) > 0


# HS-4 + HS-2: whatever the cap, narrowing as the answers say reaches every entity with its state -----------------------

@pytest.mark.parametrize("cap", [400, 900, 3000])
def test_following_the_answers_down_reaches_every_entity_under_any_cap(cap: int) -> None:
    from house_support import crawl

    rooms = ["Den", "Hall", "Loft", "Cellar"]
    devices = [device(f"Thing {i:02d}", ("light", "fan", "sensor")[i % 3], ("on", "off")[i % 2], rooms[i % 4])
               for i in range(48)]
    t, _ = tools(devices, replace(CONFIG, max_chars=cap))
    def ask_(**a: str) -> dict[str, Any]:
        return read(t, **a)

    seen = crawl(ask_)
    expected = {(d.names, d.domain, d.areas, d.value) for d in devices}
    assert seen.reached == expected
    assert max(seen.sizes) <= cap
