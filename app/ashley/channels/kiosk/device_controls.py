"""The DeviceControls service (`ashley.services`): the touch controls a device shows, the rows of `device_controls`
beside the device's own. A household's person replaces a device's whole list from the Devices room
(`ashley.api.device_controls`); the kiosk adapter reads it on every request, so an edit applies at once on both sites.
Callers import only this module and `controls`; the Postgres implementation lives beside it."""

from abc import abstractmethod

from ...services import Service
from .controls import Control


class ControlsUnavailable(Exception):
    """The database could not be reached. Transient: the caller may retry."""


class DeviceControls(Service):
    @classmethod
    def null(cls) -> "DeviceControls":
        return NullDeviceControls()

    @abstractmethod
    async def of_device(self, device_id: int, household_id: int) -> tuple[Control, ...]:
        """The device's controls in the order they are shown; empty when it has none or is not the household's. Raises
        ControlsUnavailable."""

    @abstractmethod
    async def replace(self, device_id: int, household_id: int, controls: tuple[Control, ...]) -> bool:
        """Make `controls` the whole of the unrevoked device's list; False, changing nothing, when the household has no
        such device. Logs `device_controls.replaced` with the device id and the count. Raises ControlsUnavailable."""


class NullDeviceControls(DeviceControls):
    """Reads nothing: what an unwired process sees. Raises ControlsUnavailable, so a missing registration is a 503 and
    not a screen with no buttons."""

    async def of_device(self, device_id: int, household_id: int) -> tuple[Control, ...]:
        raise ControlsUnavailable("DeviceControls is not wired")

    async def replace(self, device_id: int, household_id: int, controls: tuple[Control, ...]) -> bool:
        raise ControlsUnavailable("DeviceControls is not wired")
