"""The hallway tablet's layout and buttons as the routes carry them: `GET /api/kiosk/layout` as the Workshop's view of the
device's screen, a press that runs only what the screen's controls piece holds, and the buttons read from that piece."""

from ashley.api.kiosk_layout_models import KioskLayout
from ashley.api.models import KioskControls
from ashley.channels.kiosk.controls import Control
from ashley.workshop.model import HER, Piece, Place, Text
from ashley.workshop.screen_controls import encode
from ashley.workshop.workshop import ScreenView
from kiosk_support import DEVICE, Kiosk, kiosk as kiosk

LAMP = Control("lamp", "Lamp", "light.turn_on", "light.zq_lamp")


def laid_out() -> ScreenView:
    pieces = (Piece(4, "conversation", Text("Conversation", ""), 1, Place(0, "full"), 4),
              Piece(3, "controls", Text("Controls", encode((LAMP,))), 2, Place(1, "medium"), 7),
              Piece(1, "clock", Text("Clock", ""), 1, Place(2, "small"), 1))
    return ScreenView(DEVICE.id, True, 7, pieces, 7, {4: HER.author, 3: "person", 1: HER.author})


def test_the_layout_is_the_workshops_view_of_the_paired_devices_screen(kiosk: Kiosk) -> None:
    kiosk.device_controls.view = laid_out()
    got = kiosk.get("/api/kiosk/layout")
    assert got.status_code == 200
    body = KioskLayout.model_validate(got.json())
    assert (body.laid_out, body.seq) == (True, 7)
    assert [(p.id, p.kind, p.order, p.size) for p in body.placed] == [
        (4, "conversation", 0, "full"), (3, "controls", 1, "medium"), (1, "clock", 2, "small")]
    assert kiosk.device_controls.asked == [(DEVICE.id, DEVICE.household_id)]


def test_an_unlaid_screen_says_so_and_a_reader_that_cannot_tell_gets_503_and_an_unpaired_one_401(kiosk: Kiosk) -> None:
    unlaid = ScreenView(DEVICE.id, False, 0, laid_out().pieces, None)
    kiosk.device_controls.view = unlaid
    assert KioskLayout.model_validate(kiosk.get("/api/kiosk/layout").json()).laid_out is False
    kiosk.device_controls.down = True
    assert kiosk.get("/api/kiosk/layout").status_code == 503
    assert kiosk.get("/api/kiosk/layout", token=None).status_code == 401


def test_a_layout_read_is_not_counted_against_the_devices_rate(kiosk: Kiosk) -> None:
    for _ in range(5):
        assert kiosk.get("/api/kiosk/layout").status_code == 200
    assert kiosk.devices.counted == []


def test_the_buttons_are_the_controls_pieces_and_a_screen_with_none_has_no_buttons(kiosk: Kiosk) -> None:
    kiosk.device_controls.view = laid_out()
    got = KioskControls.model_validate(kiosk.get("/api/kiosk/controls").json())
    assert [(c.name, c.label) for c in got.controls] == [("lamp", "Lamp")]
    kiosk.device_controls.view = ScreenView(DEVICE.id, True, 8, laid_out().pieces[:1], None)
    assert kiosk.get("/api/kiosk/controls").json() == {"controls": []}
    assert kiosk.post("/api/kiosk/controls/lamp").status_code == 404


def test_a_press_runs_the_pieces_button_by_its_entity_and_a_name_it_lacks_is_404(kiosk: Kiosk) -> None:
    kiosk.device_controls.view = laid_out()
    assert kiosk.post("/api/kiosk/controls/lamp").json() == {"done": True}
    call = kiosk.tools.calls[-1]
    assert call.name == "house_do" and call.arguments == {"action": "light.turn_on", "ids": ["light.zq_lamp"]}
    before = len(kiosk.tools.calls)
    assert kiosk.post("/api/kiosk/controls/hall-light").status_code == 404 and len(kiosk.tools.calls) == before
