"""The wire models of the household page (`ashley.api.household`)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..people.fields import PROFILE_MAX
from ..people.model import Clock, UnitSystem
from ..text import NoNul


class Household(BaseModel):
    """The signed-in person's household as its people set it. `timezone` is an IANA name (`America/Denver`), the
    household's local time for anything said about the time of day. `profile` is what she always knows about the
    household, as prose (empty when none is set), at most `profile_limit` characters. `locale` is a BCP 47 tag (`en-US`)
    for how dates and numbers are written; `unit_system` the units she speaks in; `clock` whether times are written on
    a 12- or 24-hour clock. `latitude` and `longitude` are the house's own location in degrees, both null until a person
    sets one; place search reads it before Home Assistant's. `name` is set by the admin and only read here."""

    id: int
    name: str
    timezone: str
    profile: str
    profile_limit: int
    locale: str
    unit_system: UnitSystem
    clock: Clock
    latitude: float | None
    longitude: float | None


class HouseholdRequest(BaseModel):
    """Every field the household page sets, whole: a field left out is refused, never kept or cleared."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(max_length=64)
    profile: NoNul = Field(max_length=PROFILE_MAX)
    locale: str = Field(max_length=35)
    unit_system: UnitSystem
    clock: Clock
    latitude: float | None = Field(ge=-90, le=90, description="Degrees north; null clears the location")
    longitude: float | None = Field(ge=-180, le=180, description="Degrees east; null clears the location")


class HouseholdRefused(BaseModel):
    """Why nothing was stored: `invalid` names the field that is not one she can use, `timezone` (not an IANA zone
    name) or `locale` (not a BCP 47 tag of language, optional script and optional region, as `en-US`) or `location` (one of
    latitude and longitude set without the other)."""

    invalid: Literal["timezone", "locale", "location"]
    detail: str


class QuietWindow(BaseModel):
    """A daily window of whole hours in the zone `timezone` (an IANA name): from hour `start` up to, not including, hour
    `end`, each 0 to 23 and never the same. It runs across midnight when `start` is the later hour."""

    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0, le=23)
    end: int = Field(ge=0, le=23)
    timezone: str = Field(max_length=64)


class QuietHours(BaseModel):
    """The signed-in person's own quiet hours, `quiet` null when they have none. While the window holds, nothing she
    says on her own initiative reaches them; a reply to what they say is never held. A request replaces them whole,
    null clearing them."""

    model_config = ConfigDict(extra="forbid")

    quiet: QuietWindow | None


class QuietRefused(BaseModel):
    """Why nothing was stored: `invalid` is `hours` (the same hour twice) or `timezone` (not an IANA zone name)."""

    invalid: Literal["hours", "timezone"]
    detail: str
