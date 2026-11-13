"""The Screens service (`ashley.services`): which people, and which devices' screens (the kiosk), have a page open right
now, across every pod of both sites. Live's fan-out is per process, so it cannot say; this is the shared record of it.
Each open stream holds a row (`opened`, `device_opened`), refreshes it while it lives (`beat`, at the stream's heartbeat) and removes it when it ends (`closed`). A row
not refreshed within `present_s` (`live.json`) is a screen whose pod died, and counts as closed. A turn nobody is
watching uses it to decide whether to notify the person's phone as well (`decisions.md`, "Web push"); a reminder routed to
a screen, whether it was shown there (`ashley.channels.wake.screen_delivery`)."""

from abc import abstractmethod

from ..services import Service


class ScreensUnavailable(Exception):
    """The record could not be reached or written, or is not wired. Transient: whether anyone is looking is then unknown."""


class Screens(Service):
    @classmethod
    def null(cls) -> "Screens":
        return NullScreens()

    @abstractmethod
    async def opened(self, household_id: int, person_id: int) -> int:
        """Record a screen of `person_id` of `household_id` opening; its id. Also drops that person's rows left by pods that died. Raises
        ScreensUnavailable."""

    @abstractmethod
    async def device_opened(self, household_id: int, device_id: int) -> int:
        """Record a screen of the device `device_id` of `household_id` opening; its id. Also drops that device's rows left
        by pods that died. Raises ScreensUnavailable."""

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

    async def opened(self, household_id: int, person_id: int) -> int:
        raise ScreensUnavailable("screens are not wired")

    async def device_opened(self, household_id: int, device_id: int) -> int:
        raise ScreensUnavailable("screens are not wired")

    async def beat(self, screen_id: int) -> None:
        raise ScreensUnavailable("screens are not wired")

    async def closed(self, screen_id: int) -> None:
        raise ScreensUnavailable("screens are not wired")

    async def looking(self, person_id: int, within_s: float) -> bool:
        raise ScreensUnavailable("screens are not wired")

    async def showing(self, device_id: int, within_s: float) -> bool:
        raise ScreensUnavailable("screens are not wired")
