"""The Screens service (`ashley.services`): which people, and which devices' screens (the kiosk), have a page open right
now, across every pod of both sites. Live's fan-out is per process, so it cannot say; this is the shared record of it.
Each open stream holds a row (`opened`, `device_opened`), refreshes it while it lives (`beat`, at the stream's heartbeat) and removes it when it ends (`closed`). A row
not refreshed within `present_s` (`live.json`) is a screen whose pod died, and counts as closed. A turn nobody is
watching uses it to decide whether to notify the person's phone as well (`decisions.md`, "Web push"); a reminder routed to
a screen, whether it was shown there (`ashley.channels.wake.screen_delivery`).

A page names itself with a `token` it makes at load (the stream's `screen` parameter) and reports whether it is in the
foreground against that token (`person_visible`, `device_visible`); `open_screens` lists the household's open screens
with that report, which is how an announcement or a picture finds the screen someone is looking at (`decisions.md`, "Open
screens learn what changed through Live")."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal

from ..services import Service


class ScreensUnavailable(Exception):
    """The record could not be reached or written, or is not wired. Transient: whether anyone is looking is then unknown."""


@dataclass(frozen=True)
class OpenScreen:
    """One open screen: of `person_id` (their web page) or of `device_id` (a paired kiosk), exactly one of them.
    `visible` is what the page last reported, None until it has reported."""

    person_id: int | None
    device_id: int | None
    visible: bool | None

    @property
    def kind(self) -> Literal["web", "kiosk"]:
        return "web" if self.person_id is not None else "kiosk"


class Screens(Service):
    @classmethod
    def null(cls) -> "Screens":
        return NullScreens()

    @abstractmethod
    async def opened(self, household_id: int, person_id: int, token: str | None = None) -> int:
        """Record a screen of `person_id` of `household_id` opening; its id. The page reports its visibility afresh
        under its `token` once the feed is open. Also drops the household's rows left by pods that died. Raises
        ScreensUnavailable."""

    @abstractmethod
    async def device_opened(self, household_id: int, device_id: int, token: str | None = None) -> int:
        """Record a screen of the device `device_id` of `household_id` opening; its id, `token` as for `opened`. Also drops
        the household's rows left by pods that died. Raises ScreensUnavailable."""

    @abstractmethod
    async def person_visible(self, person_id: int, token: str, visible: bool) -> None:
        """The page of `person_id` that opened under `token` is in the foreground or not. Changes nothing when that
        person has no such screen open, and never another person's. Raises ScreensUnavailable."""

    @abstractmethod
    async def device_visible(self, device_id: int, token: str, visible: bool) -> None:
        """`person_visible` for a screen of the device `device_id`. Raises ScreensUnavailable."""

    @abstractmethod
    async def open_screens(self, household_id: int, within_s: float) -> tuple[OpenScreen, ...]:
        """The household's screens open or refreshed in the last `within_s`, from any pod of either site. Raises
        ScreensUnavailable."""

    @abstractmethod
    async def beat(self, screen_id: int) -> None:
        """The screen is still open. Raises ScreensUnavailable."""

    @abstractmethod
    async def closed(self, screen_id: int) -> None:
        """The screen has ended. Raises ScreensUnavailable."""

    @abstractmethod
    async def looking(self, person_id: int, within_s: float) -> bool:
        """Whether a screen of `person_id` was open or refreshed in the last `within_s`. Raises ScreensUnavailable."""

    @abstractmethod
    async def showing(self, device_id: int, within_s: float) -> bool:
        """Whether a screen of the device `device_id` was open or refreshed in the last `within_s`. Raises
        ScreensUnavailable."""


class NullScreens(Screens):
    """What an unwired process sees: every call raises, so nobody is taken to be away."""

    async def opened(self, household_id: int, person_id: int, token: str | None = None) -> int:
        raise ScreensUnavailable("screens are not wired")

    async def device_opened(self, household_id: int, device_id: int, token: str | None = None) -> int:
        raise ScreensUnavailable("screens are not wired")

    async def person_visible(self, person_id: int, token: str, visible: bool) -> None:
        raise ScreensUnavailable("screens are not wired")

    async def device_visible(self, device_id: int, token: str, visible: bool) -> None:
        raise ScreensUnavailable("screens are not wired")

    async def open_screens(self, household_id: int, within_s: float) -> tuple[OpenScreen, ...]:
        raise ScreensUnavailable("screens are not wired")

    async def beat(self, screen_id: int) -> None:
        raise ScreensUnavailable("screens are not wired")

    async def closed(self, screen_id: int) -> None:
        raise ScreensUnavailable("screens are not wired")

    async def looking(self, person_id: int, within_s: float) -> bool:
        raise ScreensUnavailable("screens are not wired")

    async def showing(self, device_id: int, within_s: float) -> bool:
        raise ScreensUnavailable("screens are not wired")
