"""The house's devices as a short list for her system prompt: for each area (those in none last), its devices' names and
domains, from the entities Home Assistant exposes to Assist (`house_entities`). Names only; state is `house_state`'s."""

from collections import defaultdict

from ..home_assistant.house import Record
from .house_entities import NO_AREA, Entity


def roster(entities: tuple[Entity, ...]) -> str:
    """One line per area, `Area: Name (domain), Name / alias (domain), ...`, areas in name order with `(no area)` last
    and devices in HA's order."""
    by_area: dict[str, list[str]] = defaultdict(list)
    for e in entities:
        by_area[e.area].append(f"{' / '.join(e.names)} ({e.domain})")
    order = sorted(by_area, key=lambda a: (a == NO_AREA, a.lower()))
    return "\n".join(f"{area}: {', '.join(by_area[area])}" for area in order)


def devices(records: tuple[Record, ...], max_chars: int) -> str:
    """The house's physical devices as one line, `Name (model)`, for her to know what exists beyond the listed entities:
    those with a maker or model (not an integration's service entry), disabled ones left out, in name order, as many as
    fit `max_chars`, then how many more there are. Empty when there are none."""
    named = sorted((r for r in records if r.fields.get("model") or r.fields.get("manufacturer")
                    if not r.fields.get("disabled")), key=lambda r: r.name.casefold())
    items = [f"{r.name} ({r.fields['model']})" if r.fields.get("model") else r.name for r in named]
    shown: list[str] = []
    for item in items:
        if len(", ".join([*shown, item])) > max_chars:
            break
        shown.append(item)
    more = len(items) - len(shown)
    return ", ".join(shown) + (f", and {more} more" if more else "")
