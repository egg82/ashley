"""A `Workshop` that answers only `screen`, for the tests that put a device's screen behind the locator: its controls piece
from a dict, or a whole view given; `down` makes it unreachable."""

from dataclasses import dataclass, field

from ashley.channels.kiosk.controls import Control
from ashley.workshop.model import HER, Piece, Place, Text
from ashley.workshop.screen_controls import encode
from ashley.workshop.workshop import NullWorkshop, ScreenView, WorkshopUnavailable

ID = 3


@dataclass
class FakeScreenControls(NullWorkshop):
    """The controls piece each (device, household) shows; `asked` records who read."""

    held: dict[tuple[int, int], tuple[Control, ...]] = field(default_factory=dict[tuple[int, int], tuple[Control, ...]])
    asked: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])
    view: ScreenView | None = None
    down: bool = False

    async def screen(self, household_id: int, device_id: int) -> ScreenView:
        self.asked.append((device_id, household_id))
        if self.down:
            raise WorkshopUnavailable("down")
        if self.view is not None:
            return self.view
        body = encode(self.held.get((device_id, household_id), ()))
        piece = Piece(ID, "controls", Text("Controls", body), 1, Place(0, "medium"), ID)
        return ScreenView(device_id, True, 5, (piece,), None, {ID: HER.author})
