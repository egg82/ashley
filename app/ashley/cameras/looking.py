"""The cameras a connection lets her look through: its `look_cameras` setting, read for the adapters of the sources that
keep it on the connection itself (Bambuddy's, a herdr bridge's)."""

from .. import services
from ..connections.connections import ConnectionsUnavailable
from ..connections.model import Opened
from ..connections.settings import SettingValue
from ..connections.settings_read import SettingsReader
from .model import CamerasFailed

LOOK_CAMERAS = "look_cameras"


async def allowed(opened: Opened) -> frozenset[str]:
    """The camera ids `opened`'s `look_cameras` names; none when it is unset or of the wrong shape. Raises CamerasFailed
    when the settings cannot be read."""
    try:
        stored = await services.get(SettingsReader).stored(opened.connection.id, opened.connection.household_id)
    except ConnectionsUnavailable as e:
        raise CamerasFailed("unreachable") from e
    return _ids(stored.values.get(LOOK_CAMERAS))


def _ids(value: SettingValue | None) -> frozenset[str]:
    return frozenset(value) if isinstance(value, list) else frozenset()
