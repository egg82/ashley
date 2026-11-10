"""Places near the house through Photon's search API (`/api/`, GeoJSON): one tool, `find_places`. Photon is biased
toward the house's coordinates rounded to `bias_decimals`, so the precise location never leaves; the results are
ranked here by great-circle distance from the precise one, nearest first. The coordinates come from `own` (the
household's own setting) read on every call, else from `home` (Home Assistant's `zone.home`), read again every
`home_ttl_s`."""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable

import httpx2
from pydantic import BaseModel, ValidationError

from ..home_assistant.zone import Coordinates, HomeUnknown
from ..inference.model import ToolCall, ToolResult
from . import searching
from .search_config import SearchConfig
from .tools import Catalogue, Tools

NAME = "find_places"
DESCRIPTION = ("Find shops, restaurants, services and other places near the house by name or kind (\"Target\", "
               "\"pharmacy\"). Returns the nearest few, nearest first, each with its kind, address and distance from "
               "the house in miles.")
_EARTH_MI = 3958.8


class _Properties(BaseModel):
    name: str | None = None
    osm_value: str | None = None
    housenumber: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None


class _Geometry(BaseModel):
    coordinates: list[float] | None = None


class _Feature(BaseModel):
    properties: _Properties
    geometry: _Geometry | None = None


class _Body(BaseModel):
    features: list[_Feature]


class PlacesTools(Tools):
    def __init__(self, http: httpx2.AsyncClient, config: SearchConfig,
                 home: Callable[[], Awaitable[Coordinates]],
                 own: Callable[[], Awaitable[Coordinates | None]] | None = None) -> None:
        """`own` answers the household's own location or None, raising HomeUnknown when it cannot be read; `home`
        answers the house's, raising HomeUnknown."""
        self._http = http
        self._config = config
        self._home = home
        self._own = own
        self._known: tuple[float, Coordinates] | None = None   # when it goes stale, and the house's coordinates
        self._reading = asyncio.Lock()

    async def catalogue(self) -> Catalogue:
        return Catalogue((searching.spec(NAME, DESCRIPTION),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        if call.name != NAME:
            return searching.unknown(call, started)
        query = searching.query(call)
        if query is None:
            return searching.failed(call, "error", started, "find_places needs a query")
        try:
            house = await self._house()
        except HomeUnknown:
            return searching.failed(call, "unavailable", started, "the house's location is unknown")
        try:
            body = _Body.model_validate_json(await searching.get(
                self._http, self._config.photon_url + "/api/", self._params(query, house), self._config.timeout_s))
        except (searching.NoAnswer, ValidationError):
            return searching.failed(call, "unavailable", started, "places search did not answer")
        places = _nearest(body.features, house)[:self._config.places_results]
        return searching.ok(call, started, {"places": places}, len(places))

    async def _house(self) -> Coordinates:
        """The household's own coordinates when set, else the house's, read at most once per `home_ttl_s`; a failure is
        not kept. Raises HomeUnknown."""
        if self._own is not None:
            located = await self._own()
            if located is not None:
                return located
        async with self._reading:
            if self._known is None or time.monotonic() >= self._known[0]:
                house = await self._home()
                self._known = (time.monotonic() + self._config.home_ttl_s, house)
            return self._known[1]

    def _params(self, query: str, house: Coordinates) -> dict[str, str | int | float]:
        decimals = self._config.bias_decimals
        return {"q": query, "lat": round(house.latitude, decimals), "lon": round(house.longitude, decimals),
                "limit": self._config.places_fetched}


def _nearest(features: list[_Feature], house: Coordinates) -> list[dict[str, object]]:
    """The features with a name and a point, as places, nearest `house` first."""
    found: list[tuple[float, dict[str, object]]] = []
    for feature in features:
        point = feature.geometry.coordinates if feature.geometry is not None else None
        if not feature.properties.name or point is None or len(point) < 2:
            continue
        miles = distance_mi(house, Coordinates(point[1], point[0]))
        found.append((miles, _place(feature.properties, miles)))
    found.sort(key=lambda pair: pair[0])
    return [place for _, place in found]


def _place(p: _Properties, miles: float) -> dict[str, object]:
    place: dict[str, object] = {"name": p.name}
    if p.osm_value:
        place["kind"] = p.osm_value
    line = " ".join(part for part in (p.housenumber, p.street) if part)
    address = ", ".join(part for part in (line, p.city, p.state) if part)
    if address:
        place["address"] = address
    place["distance_mi"] = round(miles, 1)
    return place


def distance_mi(a: Coordinates, b: Coordinates) -> float:
    """Great-circle (haversine) distance in miles."""
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat, dlon = lat2 - lat1, math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_MI * math.asin(min(1.0, math.sqrt(h)))
