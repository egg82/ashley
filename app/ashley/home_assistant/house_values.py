"""A household's Home Assistant settings (`kind.HOME_ASSISTANT.settings`) as her house tools read them: which reads
count as the household's or a trusted service's own words, which scripts only look something up, and which things are
always asked about. Read once per turn (`read`); a setting that is missing, or unreadable, is empty, which is the least
trust: every read is outside words and only the general tier rules judge a change."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from .. import services
from ..connections.settings import SettingValue, SettingValues
from ..connections.settings_read import SettingsReader

HOUSEHOLD_READS = "household_reads"
SERVICE_READS = "service_reads"
READS = "reads"
CONSEQUENTIAL = "consequential_entities"
GLANCE_CALENDARS = "glance_calendars"


@dataclass(frozen=True)
class HouseValues:
    """`household_reads`: for a read action, the entities whose response only the household writes. `service_reads`:
    reads whose response a trusted service writes. `reads`: scripts that change nothing though the house does not say.
    `consequential`: entities always judged. `glance_calendars`: the calendars the kiosk's glance shows."""

    household_reads: Mapping[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    service_reads: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    consequential: tuple[str, ...] = ()
    glance_calendars: tuple[str, ...] = ()


def of(values: SettingValues) -> HouseValues:
    """The settings as the tools read them; a value of the wrong shape is empty."""
    per_action = values.get(HOUSEHOLD_READS)
    return HouseValues({a: tuple(ids) for a, ids in per_action.items()} if isinstance(per_action, dict) else {},
                       _ids(values.get(SERVICE_READS)), _ids(values.get(READS)), _ids(values.get(CONSEQUENTIAL)),
                       _ids(values.get(GLANCE_CALENDARS)))


def _ids(value: SettingValue | None) -> tuple[str, ...]:
    return tuple(value) if isinstance(value, list) else ()


async def read(household_id: int) -> HouseValues:
    """The household's Home Assistant settings now. Never raises: unreadable settings are empty."""
    return of(await services.get(SettingsReader).of(household_id, "house"))
