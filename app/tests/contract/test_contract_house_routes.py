"""A person's house routes: the household's lights and scenes listed and pressed from a signed-in screen, and the house at
a glance. A press is carried out by the same tool a kiosk's is, so the tool's own refusals apply; it is the person's act and
counts against their rate."""

from dataclasses import replace

import pytest
from ashley import logs
from ashley.api.house_models import HouseControlList, HouseGlance
from ashley.channels.kiosk.controls import ACTIONS
from ashley.home_assistant import irreversible
from ashley.home_assistant.house import HouseUnavailable
from ashley.printing.model import NotConnected, PrintingFailed, PrintingUnavailable
from ashley.tools.house_act import Rules
from house_routes_support import OTHER, OTHER_HOME, World, printer, work_item, world as world
from kiosk_support import HOME, Kiosk, kiosk as kiosk
from web_chat_support import error_of


def listed(world: World, person: int = 1) -> dict[str, str | None]:
    got = world.get("/api/house/controls", person)
    assert got.status_code == 200
    return {c.name: c.label for c in HouseControlList.model_validate(got.json()).controls}


# ---- GET /api/house/controls ----------------------------------------------------------------------------------------

def test_only_lights_and_scenes_are_listed_each_with_a_stable_name(world: World) -> None:
    assert listed(world) == {"light-zq-hall": "Hall", "light-zq-porch-lamp": "Porch", "scene-zq-night": "Night"}


def test_every_listed_control_is_an_action_the_kiosk_may_run(world: World) -> None:
    from ashley.channels.kiosk.house_controls import of_entities
    found = of_entities(world.catalogues[HOME])
    assert found and all(c.action in ACTIONS for c in found)
    assert {c.action for c in found} == {"light.toggle", "scene.turn_on"}


def test_a_light_shows_whether_it_is_on_and_a_scene_or_an_unknown_light_shows_null(world: World) -> None:
    world.homes.houses[HOME].things = [t for t in world.homes.houses[HOME].things if t.id != "light.zq_porch_lamp"]
    world.homes.houses[HOME].things[0] = replace(world.homes.houses[HOME].things[0], state="on")
    got = HouseControlList.model_validate(world.get("/api/house/controls").json())
    assert {c.name: c.on for c in got.controls} == {"light-zq-hall": True, "light-zq-porch-lamp": None, "scene-zq-night": None}


def test_a_house_that_cannot_be_read_still_lists_the_controls_with_no_state(world: World) -> None:
    world.homes.down = True
    got = HouseControlList.model_validate(world.get("/api/house/controls").json())
    assert len(got.controls) == 3 and all(c.on is None for c in got.controls)


def test_an_entity_whose_name_does_not_fit_or_clashes_is_left_out() -> None:
    from ashley.channels.kiosk.house_controls import of_entities
    from ashley.connections.model import CatalogueEntity as E
    got = of_entities([E("light.a_b", "One", "light", None), E("light.a.b", "Two", "light", None), E("light.ok", " ", "light", None),
                       E("light." + "x" * 40, "Long", "light", None), E("switch.a", "S", "switch", None)])
    assert [(c.id, c.label) for c in got] == [("light-ok", "light.ok")]


def test_each_household_lists_its_own(world: World) -> None:
    assert listed(world, OTHER.id) == {"light-zq-hall": "Their hall", "light-zq-other": "Other"}


# ---- POST /api/house/controls/{name} --------------------------------------------------------------------------------

def test_a_press_runs_the_tool_the_kiosk_runs_on_the_named_entity(world: World) -> None:
    got = world.post("/api/house/controls/light-zq-hall")
    assert got.status_code == 200 and got.json() == {"done": True}
    assert [(a, ids) for _, _, a, ids, _ in world.homes.houses[HOME].done] == [("light.toggle", ("light.zq_hall",))]
    assert world.everyday.asked == [HOME]


def test_a_scene_is_pressed_with_its_own_action(world: World) -> None:
    assert world.post("/api/house/controls/scene-zq-night").json() == {"done": True}
    assert [(a, ids) for _, _, a, ids, _ in world.homes.houses[HOME].done] == [("scene.turn_on", ("scene.zq_night",))]


def test_a_press_the_tool_judges_irreversible_is_refused_and_does_nothing(world: World) -> None:
    world.everyday.rules = Rules((), (), irreversible.parse({"operations": ["perform:light.toggle"]}))
    got = world.post("/api/house/controls/light-zq-hall")
    assert got.status_code == 200 and got.json() == {"done": False}
    assert world.homes.houses[HOME].done == []


@pytest.mark.parametrize("name", ["switch-zq-oven", "lock-zq-front", "light-nowhere", "light-zq-other", "scene-zq-hall"])
def test_a_name_that_is_not_a_light_or_scene_of_the_household_is_404_and_does_nothing(world: World, name: str) -> None:
    got = world.post(f"/api/house/controls/{name}")
    assert got.status_code == 404 and error_of(got).code == "not_found"
    assert world.homes.houses[HOME].done == [] and world.kiosk.sessions.counted == []


@pytest.mark.parametrize("name", ["Light-zq-hall", "light.zq_hall", "x" * 41])
def test_a_name_outside_the_alphabet_is_422(world: World, name: str) -> None:
    assert world.post(f"/api/house/controls/{name}").status_code == 422
    assert world.homes.houses[HOME].done == []


def test_a_body_cannot_change_what_is_pressed(world: World) -> None:
    world.post("/api/house/controls/light-zq-hall", body={"action": "lock.unlock", "ids": ["lock.zq_front"]})
    assert [(a, ids) for _, _, a, ids, _ in world.homes.houses[HOME].done] == [("light.toggle", ("light.zq_hall",))]


def test_a_person_of_another_household_cannot_press_this_ones_name_and_presses_their_own(world: World) -> None:
    assert world.post("/api/house/controls/light-zq-porch-lamp", OTHER.id).status_code == 404
    assert world.homes.houses[HOME].done == [] and world.homes.houses[OTHER_HOME].done == []
    assert world.post("/api/house/controls/light-zq-hall", OTHER.id).json() == {"done": True}
    assert world.homes.houses[HOME].done == [] and len(world.homes.houses[OTHER_HOME].done) == 1


def test_the_press_names_the_person_in_the_log_and_is_not_an_outside_action(world: World,
                                                                         capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    assert world.post("/api/house/controls/light-zq-hall", 2).json() == {"done": True}   # NeverRecorded fails a record
    seen = capsys.readouterr()
    line = next(l for l in (seen.out + seen.err).splitlines() if "event=kiosk.control" in l)
    assert "person=2" in line and "control=light-zq-hall" in line and "outcome=ok" in line and "device=" not in line


def test_the_kiosk_press_still_names_its_device(kiosk: Kiosk, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    kiosk.post("/api/kiosk/controls/hall-light")
    seen = capsys.readouterr()
    line = next(l for l in (seen.out + seen.err).splitlines() if "event=kiosk.control" in l)
    assert "device=9" in line and "person=" not in line


# ---- auth, site and rate --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [("GET", "/api/house/controls"), ("POST", "/api/house/controls/light-zq-hall"),
                                         ("GET", "/api/house/glance")])
def test_no_session_or_a_stale_one_is_401(world: World, method: str, path: str) -> None:
    from web_chat_support import JSON
    for cookie in ({}, {"cookie": "__Host-ashley_session=t-999"}, {"cookie": "__Host-ashley_kiosk=zqTOKEN-kiosk-5521"}):
        got = world.kiosk.app.request(method, path, headers={**JSON, **cookie}, json={} if method == "POST" else None)
        assert got.status_code == 401 and error_of(got).code == "unauthorized"
    assert world.homes.houses[HOME].done == [] and world.kiosk.sessions.counted == []


def test_a_press_from_another_site_or_not_json_is_403_and_does_nothing(world: World) -> None:
    path = "/api/house/controls/light-zq-hall"
    got = world.post(path, headers={"origin": "https://evil.test"})
    assert got.status_code == 403 and error_of(got).code == "forbidden"
    plain = world.kiosk.app.post(path, content=b"x", headers={"content-type": "text/plain", "origin": "https://ashley.test",
                                                              "cookie": "__Host-ashley_session=t-1"})
    assert plain.status_code == 403
    assert world.homes.houses[HOME].done == [] and world.kiosk.sessions.counted == []


def test_each_press_counts_against_the_person_and_reads_never_do(world: World) -> None:
    for path in ("/api/house/controls", "/api/house/glance"):
        world.get(path)
    assert world.kiosk.sessions.counted == []
    world.post("/api/house/controls/light-zq-hall", 1)
    world.post("/api/house/controls/scene-zq-night", 2)
    assert world.kiosk.sessions.counted == [1, 2]


def test_over_the_rate_is_429_and_does_nothing(world: World) -> None:
    world.kiosk.sessions.over = True
    got = world.post("/api/house/controls/light-zq-hall")
    assert got.status_code == 429 and error_of(got).code == "rate_limited"
    assert world.homes.houses[HOME].done == []
    assert world.get("/api/house/controls").status_code == 200


def test_sessions_down_is_503_on_a_press_and_does_nothing(world: World) -> None:
    world.kiosk.sessions.down = True
    assert world.post("/api/house/controls/light-zq-hall").status_code == 503
    assert world.homes.houses[HOME].done == []


def test_a_catalogue_that_cannot_be_read_is_503(world: World) -> None:
    from ashley.connections.connections import ConnectionsUnavailable

    async def down(household_id: int, person_id: int) -> list[object]:
        raise ConnectionsUnavailable("down")
    world.patch.setattr("ashley.channels.kiosk.house_controls.entities", down)
    assert world.get("/api/house/controls").status_code == 503
    assert world.post("/api/house/controls/light-zq-hall").status_code == 503
    assert world.homes.houses[HOME].done == [] and world.kiosk.sessions.counted == []


# ---- GET /api/house/glance ------------------------------------------------------------------------------------------

def glance(world: World) -> HouseGlance:
    got = world.get("/api/house/glance")
    assert got.status_code == 200
    return HouseGlance.model_validate(got.json())


def test_the_glance_names_who_is_home_as_the_kiosk_does(world: World) -> None:
    world.kiosk.presence.at_home = frozenset({12, 1})
    assert glance(world).home == ["Alana", "Twelve"]
    world.kiosk.presence.at_home = None
    assert glance(world).home is None


def test_needs_attention_counts_what_waits_on_the_person_the_printers_that_fault_and_a_readable_house(world: World) -> None:
    world.waiting = [work_item("waiting_on_you"), work_item("running"), work_item("waiting_on_you")]
    world.printing.error = None
    world.printing.rows = (printer("a", "hms"), printer("b"), printer("c", "x", "y"))
    assert glance(world).needs_attention.model_dump() == {"waiting_on_you": 2, "printer_faults": 2, "house_unreadable": False}


def test_nothing_waiting_and_no_faults_is_zero_not_unknown(world: World) -> None:
    world.printing.error = None
    world.printing.rows = (printer("a"),)
    assert glance(world).needs_attention.model_dump() == {"waiting_on_you": 0, "printer_faults": 0, "house_unreadable": False}


def test_what_cannot_be_read_is_unknown_never_zero_or_false(world: World) -> None:
    from ashley.errands.errands import ErrandsUnavailable
    world.waiting = ErrandsUnavailable("down")
    world.homes.houses.pop(HOME)
    got = glance(world).needs_attention
    assert got.model_dump() == {"waiting_on_you": None, "printer_faults": None, "house_unreadable": None}


@pytest.mark.parametrize("error", [PrintingFailed("unreachable"), PrintingUnavailable("down"), NotConnected()])
def test_printers_that_cannot_be_read_are_unknown(world: World, error: Exception) -> None:
    world.printing.error = error
    assert glance(world).needs_attention.printer_faults is None


def test_more_printers_than_were_read_is_unknown(world: World) -> None:
    world.printing.error = None
    world.printing.rows = (printer("a", "x"),)
    world.printing.total = 80
    assert glance(world).needs_attention.printer_faults is None


def test_a_house_that_does_not_answer_is_unreadable_and_one_that_is_down_in_the_registry_is_too(world: World) -> None:
    world.homes.houses[HOME].down = True
    assert glance(world).needs_attention.house_unreadable is True
    world.homes.houses[HOME].down = False
    world.homes.down = True
    assert glance(world).needs_attention.house_unreadable is True


def test_the_glance_carries_nothing_but_what_the_model_names(world: World) -> None:
    assert set(world.get("/api/house/glance").json()) == set(HouseGlance.model_fields)
