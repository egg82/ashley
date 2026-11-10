"""`house_state` past its cap: no answer is longer than `max_chars`, a level that does not fit says so (`complete`
false, `narrow_by`) while still listing every child, and every entity of a house far larger than the cap is reached
by drilling down as the description says. The control proves the crawl catches an answer cut silently."""

import json
from dataclasses import replace
from typing import Any

import pytest

from ashley.tools import house_state_config
from ashley.tools.house_state import HouseStateTools
from house_support import Device, ask, crawl, device, house_of, read, tools

SMALL = replace(house_state_config.load(), max_chars=420)
KINDS = ("temperature", "humidity", "battery")


def big_house(areas: int = 6, per_area: int = 5, loose: int = 18) -> list[Device]:
    out: list[Device] = []
    for a in range(areas):
        out += [device(f"Lamp {a}-{i}", "light", "on" if i % 2 else "off", f"Room {a}") for i in range(per_area)]
        out.append(device(f"Air {a}", "sensor", f"{20 + a}.5", f"Room {a}", device_class="temperature"))
    out += [device(f"Gauge {i}", "sensor", str(i), None, device_class=KINDS[i % 3], unit_of_measurement="%")
            for i in range(loose)]
    out += [device(f"Plug {i}", "switch", "on", None) for i in range(loose // 3)]
    return out


def everything(devices: list[Device]) -> set[tuple[str, str, str, str]]:
    return {(d.names, d.domain, d.areas or "(no area)", d.value) for d in devices}


def test_every_entity_is_reachable_by_drilling_down_and_no_answer_passes_the_cap() -> None:
    devices = big_house()
    assert len(str(devices)) > 4 * SMALL.max_chars
    tool = tools(devices, SMALL)[0]

    def asking(**arguments: str) -> dict[str, Any]:
        return read(tool, **arguments)
    seen = crawl(asking)
    assert seen.reached == everything(devices)
    assert max(seen.sizes) <= SMALL.max_chars
    assert read(tool)["complete"] is False


def test_control_an_answer_cut_silently_is_caught_by_the_crawl() -> None:
    devices = big_house()
    tool = tools(devices, SMALL)[0]

    def cut(**arguments: Any) -> dict[str, Any]:
        body = read(tool, **arguments)
        for key in ("areas", "domains", "entities", "groups"):
            if isinstance(body.get(key), list):
                body[key] = body[key][:2]
        return body
    assert crawl(cut).reached != everything(devices)


def test_a_house_over_the_cap_lists_every_area_in_counts_and_says_to_narrow_by_area() -> None:
    devices = big_house()
    body = read(tools(devices, SMALL)[0])
    assert body["complete"] is False and body["narrow_by"] == ["area"]
    assert [a["area"] for a in body["areas"]] == [f"Room {a}" for a in range(6)] + ["(no area)"]
    assert sum(a["count"] for a in body["areas"]) == len(devices)


def test_entities_over_the_cap_are_listed_by_name_in_groups_or_counted_by_kind_and_add_up() -> None:
    devices = big_house(loose=24)
    named = read(tools(devices, replace(SMALL, max_chars=700))[0], area="(no area)", domain="sensor")
    assert named["complete"] is False and named["narrow_by"] == ["name"] and named["matched"] == 24
    assert sorted(n for g in named["groups"] for n in g["names"]) == sorted(f"Gauge {i}" for i in range(24))
    counted = read(tools(devices, SMALL)[0], area="(no area)", domain="sensor")
    assert counted["complete"] is False and counted["narrow_by"] == ["name"]
    assert sum(g["count"] for g in counted["groups"]) == 24 and {g["kind"] for g in counted["groups"]} == set(KINDS)


def test_at_the_shipped_cap_a_large_house_still_lists_every_area() -> None:
    devices = big_house(areas=60, per_area=1, loose=0)
    tool = HouseStateTools(house_of(devices), house_state_config.load())
    result = tool_answer(tool)
    assert len(result) <= house_state_config.load().max_chars
    body = json.loads(result)
    assert body["complete"] is False and len(body["areas"]) == 60


def tool_answer(tool: HouseStateTools) -> str:
    return json.dumps(read(tool), separators=(",", ":"), ensure_ascii=False)


def test_an_answer_over_the_cap_is_logged_as_capped(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="ashley.tools"):
        read(tools(big_house(), SMALL)[0])
        read(tools(big_house(), SMALL)[0], area="Room 1")
    fields = [getattr(r, "fields") for r in caplog.records if r.getMessage() == "tools.call"]
    assert [(f["level"], f["children"], f["capped"]) for f in fields] == [("house", 7, True), ("area", 2, False)]


def test_a_name_matching_nothing_in_a_house_over_the_cap_still_fits_and_lists_every_area() -> None:
    result = ask(tools(big_house(), SMALL)[0], name="garage")
    assert len(result.content) <= SMALL.max_chars
    body = json.loads(result.content)
    assert body["matched"] == 0 and len(body["house"]["areas"]) == 7 and body["house"]["complete"] is False
