"""Contract 16, 18 and 19 through the real app: the kiosk's layout read, the Devices room's versioned controls, and the
kiosk's buttons read from the screen's controls piece."""

from ashley import services
from ashley.workshop.commands import Remove
from ashley.workshop.model import By
from ashley.workshop.workshop import NullWorkshop, ScreenView, Workshop
from contract.conversations_support import scalar
from sb_rig import HALL, NIGHT, PORCH, Rig
from sb_support import CONTROLS, benches_of, put_rows
from sb_support import HALL as HALL_ROW

SEED = [{"id": 1, "kind": "clock", "order": 0, "size": "small"}, {"id": 2, "kind": "home", "order": 1, "size": "small"},
        {"id": 3, "kind": "controls", "order": 2, "size": "medium"},
        {"id": 4, "kind": "conversation", "order": 3, "size": "full"}]


def screen_of(app: Rig, device: int) -> ScreenView:
    return app.on_loop(lambda: services.get(Workshop).screen(app.people.home, device))


def version(app: Rig, device: int) -> int:
    return int(app.controls(device)["piece_version"])


def names(app: Rig, token: str) -> list[str]:
    got = app.kiosk("/api/kiosk/controls", token)
    assert got.status_code == 200, got.text
    return [c["name"] for c in got.json()["controls"]]


def drop_controls_piece(app: Rig, device: int) -> None:
    app.on_loop(lambda: services.get(Workshop).apply_screen(app.people.home, device, Remove(By(app.people.alana), CONTROLS)))


def performed(app: Rig) -> list[tuple[str, tuple[str, ...]]]:
    return [(d[2], d[3]) for d in app.house.done]


def test_k16_an_unlaid_screen_is_served_as_its_seed_and_nothing_is_written(app: Rig) -> None:
    device, token = app.tablet()
    got = app.kiosk("/api/kiosk/layout", token)
    assert got.status_code == 200, got.text
    assert got.json() == {"laid_out": False, "seq": 0, "placed": SEED}
    assert benches_of(app.url, device) == [] and app.live.published == []


def test_k16_a_laid_out_screen_is_served_as_the_workshops_view(app: Rig) -> None:
    device, token = app.tablet()
    assert app.put_controls(device, 0, HALL).status_code == 200
    view = screen_of(app, device)
    got = app.kiosk("/api/kiosk/layout", token).json()
    assert got["laid_out"] is True and got["seq"] == view.seq == 5
    assert got["placed"] == [{"id": p.id, "kind": p.kind, "order": p.place.order, "size": p.place.size} for p in view.pieces]


def test_k16_each_tablet_reads_its_own_screen(app: Rig) -> None:
    one, first = app.tablet()
    two, second = app.tablet()
    assert app.put_controls(one, 0, HALL).status_code == 200
    assert app.kiosk("/api/kiosk/layout", first).json()["laid_out"] is True
    assert app.kiosk("/api/kiosk/layout", second).json()["laid_out"] is False
    assert benches_of(app.url, two) == []


def test_k16_an_unpaired_screen_is_401(app: Rig) -> None:
    app.tablet(token="paired-token")
    for token in (None, "not-a-token"):
        got = app.kiosk("/api/kiosk/layout", token)
        assert got.status_code == 401 and got.json()["code"] == "unauthorized"


def test_k16_an_unavailable_workshop_is_503(app: Rig) -> None:
    _, token = app.tablet()
    assert app.kiosk("/api/kiosk/layout", token).status_code == 200
    services.register(Workshop, NullWorkshop())
    got = app.kiosk("/api/kiosk/layout", token)
    assert got.status_code == 503 and got.json()["code"] == "unavailable"


def test_k16_reading_the_layout_is_never_counted_against_the_devices_rate(app: Rig) -> None:
    _, token = app.tablet()
    assert {app.kiosk("/api/kiosk/layout", token).status_code for _ in range(70)} == {200}


def test_k18_a_screen_not_yet_laid_out_has_controls_version_0(app: Rig) -> None:
    device, _ = app.tablet()
    assert app.controls(device) == {"device_controls": [], "piece_version": 0}


def test_k18_the_first_put_on_an_unlaid_screen_with_base_version_0_stores_the_list(app: Rig) -> None:
    device, token = app.tablet()
    got = app.put_controls(device, 0, PORCH, HALL)
    assert got.status_code == 200, got.text
    assert [c["name"] for c in app.controls(device)["device_controls"]] == ["porch-off", "hall-light"]
    assert names(app, token) == ["porch-off", "hall-light"] and version(app, device) >= 1


def test_k18_the_current_base_version_stores_the_list_and_bumps_the_version_by_one(app: Rig) -> None:
    device, _ = app.tablet()
    app.put_controls(device, 0, PORCH)
    seen = version(app, device)
    got = app.put_controls(device, seen, PORCH, HALL, NIGHT)
    assert got.status_code == 200, got.text
    assert version(app, device) == seen + 1
    assert [c["name"] for c in app.controls(device)["device_controls"]] == ["porch-off", "hall-light", "night"]


def test_k18_a_stale_base_version_is_409_stale_and_stores_nothing(app: Rig) -> None:
    device, _ = app.tablet()
    app.put_controls(device, 0, PORCH)
    old = version(app, device)
    assert app.put_controls(device, old, HALL).status_code == 200
    before = app.controls(device)
    got = app.put_controls(device, old, NIGHT)
    assert got.status_code == 409 and got.json()["code"] == "stale"
    assert app.controls(device) == before
    assert [c["name"] for c in app.controls(device)["device_controls"]] == ["hall-light"]


def test_k18_two_editors_who_read_the_same_version_are_resolved_by_the_second_being_refused(app: Rig) -> None:
    device, _ = app.tablet()
    app.put_controls(device, 0, PORCH)
    seen = version(app, device)
    app.as_("alana")
    assert app.put_controls(device, seen, HALL).status_code == 200
    app.as_("sam")
    assert app.put_controls(device, seen, NIGHT).status_code == 409
    assert [c["name"] for c in app.controls(device)["device_controls"]] == ["hall-light"]


def test_k18_base_version_0_on_a_screen_with_no_controls_piece_adds_one(app: Rig) -> None:
    device, token = app.tablet()
    app.put_controls(device, 0, PORCH)
    drop_controls_piece(app, device)
    assert version(app, device) == 0 and app.controls(device)["device_controls"] == []
    got = app.put_controls(device, 0, HALL)
    assert got.status_code == 200, got.text
    assert sum(p.kind == "controls" for p in screen_of(app, device).pieces) == 1
    assert names(app, token) == ["hall-light"] and version(app, device) >= 1


def test_k18_a_put_without_base_version_is_refused_by_validation_and_stores_nothing(app: Rig) -> None:
    device, _ = app.tablet()
    assert app.put_controls(device, None, HALL).status_code == 422
    assert benches_of(app.url, device) == []


def test_k18_a_light_the_house_lacks_is_still_422_and_leaves_the_version(app: Rig) -> None:
    device, _ = app.tablet()
    app.put_controls(device, 0, HALL)
    seen = version(app, device)
    bad = {**PORCH, "entity_id": "light.zq_nowhere"}
    got = app.put_controls(device, seen, bad)
    assert got.status_code == 422 and got.json()["reason"] == "unknown_entity"
    assert version(app, device) == seen


def test_k19_a_press_reads_the_controls_piece_a_name_in_it_runs_house_do_with_its_entity(app: Rig) -> None:
    device, token = app.tablet()
    app.put_controls(device, 0, HALL, PORCH)
    assert app.kiosk("/api/kiosk/controls", token).json() == {"controls": [
        {"name": "hall-light", "label": "Hall light", "on": None}, {"name": "porch-off", "label": "Porch off", "on": None}]}
    got = app.kiosk("/api/kiosk/controls/hall-light", token, "POST")
    assert got.status_code == 200 and got.json() == {"done": True}
    assert performed(app) == [("light.turn_on", ("light.zq_hall",))]
    assert app.kiosk("/api/kiosk/controls/porch-off", token, "POST").json() == {"done": True}
    assert performed(app)[-1] == ("light.turn_off", ("light.zq_porch",))


def test_k19_a_name_not_in_the_piece_is_404_and_the_house_is_not_asked(app: Rig) -> None:
    device, token = app.tablet()
    app.put_controls(device, 0, HALL)
    got = app.kiosk("/api/kiosk/controls/night", token, "POST")
    assert got.status_code == 404 and got.json()["code"] == "not_found"
    assert performed(app) == []


def test_k19_an_edit_of_the_piece_applies_to_the_next_press(app: Rig) -> None:
    device, token = app.tablet()
    app.put_controls(device, 0, HALL)
    app.put_controls(device, version(app, device), NIGHT)
    assert names(app, token) == ["night"]
    assert app.kiosk("/api/kiosk/controls/hall-light", token, "POST").status_code == 404
    assert app.kiosk("/api/kiosk/controls/night", token, "POST").json() == {"done": True}
    assert performed(app) == [("scene.turn_on", ("scene.zq_night",))]


def test_k19_a_screen_with_no_controls_piece_has_no_buttons_and_a_press_is_404(app: Rig) -> None:
    device, token = app.tablet()
    app.put_controls(device, 0, HALL)
    drop_controls_piece(app, device)
    assert app.kiosk("/api/kiosk/controls", token).json() == {"controls": []}
    assert app.kiosk("/api/kiosk/controls/hall-light", token, "POST").status_code == 404
    assert performed(app) == []


def test_k19_a_device_not_yet_laid_out_shows_and_runs_its_rows_without_creating_a_bench(app: Rig) -> None:
    device, token = app.tablet()
    put_rows(app.url, device, app.people.home, HALL_ROW)
    assert names(app, token) == ["hall-light"]
    assert app.kiosk("/api/kiosk/controls/hall-light", token, "POST").json() == {"done": True}
    assert benches_of(app.url, device) == []
    assert int(scalar(app.url, "SELECT count(*) FROM device_controls WHERE device_id = %s", (device,))) == 1


def test_k19_a_press_is_read_from_the_tablets_own_screen_only(app: Rig) -> None:
    one, first = app.tablet()
    _, second = app.tablet()
    app.put_controls(one, 0, HALL)
    assert names(app, first) == ["hall-light"] and names(app, second) == []
    assert app.kiosk("/api/kiosk/controls/hall-light", second, "POST").status_code == 404
