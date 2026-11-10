"""A thing in the house as `house_query` matches it and `house_render` and `house_roster` show it: its names (its
name, then its aliases), domain, state, areas (its area's name, then the area's aliases) and scalar attributes."""

from collections.abc import Mapping
from dataclasses import dataclass

NO_AREA = "(no area)"
"""The area an entity in none is listed under, and the `area` value that asks for them."""

Scalar = str | int | float | bool | None


@dataclass(frozen=True)
class Entity:
    names: tuple[str, ...]           # its name, then its aliases
    domain: str
    state: str
    areas: tuple[str, ...]           # its area's name, then the area's aliases; empty when in no area
    attributes: Mapping[str, Scalar]
    id: str = ""                     # the house's own id for it; empty when the source gives none
    featured: bool = True            # listed for her by name up front; a source that lists only those leaves it so

    @property
    def area(self) -> str:
        return self.areas[0] if self.areas else NO_AREA
