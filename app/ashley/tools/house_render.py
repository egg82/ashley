"""`house_state`'s answer: the level the query asks for, every one of its children summarised, as compact JSON no longer
than `max_chars`. The levels are the house (its areas), an area (its domains) and entities (the matched ones, with
their states). Each level has forms from most to least detail; the first that fits is the answer. A list in an answer
always holds every child: a form that cannot show each in full shows each by name only (entities) or as a count, with
`complete` false and `narrow_by` naming the arguments that split it, and the smallest form holds only totals. Nothing
is ever dropped from a list to make it fit. An entity in a full list carries when its state last changed
(`ashley.stamp.stamp` in the household's `zone`), left out when either is unknown."""

import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import tzinfo

from ..stamp import stamp
from .house_entities import Entity
from .house_query import Query, Selection, select
from .house_state_config import HouseStateConfig

Body = dict[str, object]


@dataclass(frozen=True)
class Answer:
    text: str
    level: str
    children: int     # the level's children: areas, domains, or the entities matched
    capped: bool      # the level did not fit in full, so it was answered in counts
    outside: bool = False  # it shows attributes of a thing in an `outside_domains` domain


def answer(entities: tuple[Entity, ...], query: Query, config: HouseStateConfig, zone: tzinfo | None = None) -> Answer:
    selection = select(entities, query)
    if not selection.entities:
        return Answer(_json(_nothing(entities, query, selection, config)), query.level, 0, False)
    chosen = selection.entities
    if query.level == "house":
        forms, children = _house(chosen, config), len(_by(chosen, _area_key))
    elif query.level == "area":
        forms, children = _area(chosen, config), len(_by(chosen, lambda e: e.domain))
    else:
        forms, children = _entities(chosen, query, zone), len(chosen)
    for form in forms[:-1]:
        text = _json(form)
        if len(text) <= config.max_chars:
            return Answer(text, query.level, children, form["complete"] is False, _shows_attributes(form, chosen, config))
    return Answer(_json(forms[-1]), query.level, children, True)


def _shows_attributes(form: Body, chosen: tuple[Entity, ...], config: HouseStateConfig) -> bool:
    return "entities" in form and any(e.domain in config.outside_domains for e in chosen)


def _house(chosen: tuple[Entity, ...], config: HouseStateConfig) -> list[Body]:
    areas = _by(chosen, _area_key)
    return [
        {"level": "house", "complete": True,
         "areas": [{"area": _label(ms), "summary": _area_summary(ms, config)} for ms in areas.values()]},
        {"level": "house", "complete": False, "narrow_by": ["area"],
         "areas": [{"area": _label(ms), "count": len(ms)} for ms in areas.values()]},
        {"level": "house", "complete": False, "narrow_by": ["name", "domain"],
         "area_count": len(areas), "entity_count": len(chosen)},
    ]


def _area(chosen: tuple[Entity, ...], config: HouseStateConfig) -> list[Body]:
    domains = _by(chosen, lambda e: e.domain)
    area = ", ".join(sorted({e.area for e in chosen}, key=str.casefold))
    return [
        {"level": "area", "area": area, "complete": True,
         "domains": [{"domain": d, "summary": _summary(d, ms, config)} for d, ms in domains.items()]},
        {"level": "area", "area": area, "complete": False, "narrow_by": ["domain", "name"],
         "domains": [{"domain": d, "count": len(ms)} for d, ms in domains.items()]},
        {"level": "area", "area": area, "complete": False, "narrow_by": ["domain", "name"],
         "domain_count": len(domains), "entity_count": len(chosen)},
    ]


def _entities(chosen: tuple[Entity, ...], query: Query, zone: tzinfo | None) -> list[Body]:
    ordered = sorted(chosen, key=lambda e: (_area_key(e), e.domain, e.names[0].casefold()))
    narrow = [a for a in ("area", "domain") if a not in query.given()] + ["name"]
    groups = list(_by(ordered, lambda e: (_area_key(e), e.domain, _device_class(e) or "")).values())
    return [
        {"level": "entities", "matched": len(chosen), "complete": True, "entities": [_entity(e, zone) for e in ordered]},
        {"level": "entities", "matched": len(chosen), "complete": False, "narrow_by": narrow,
         "groups": [{**_group(ms), "names": [e.names[0] for e in ms]} for ms in groups]},
        {"level": "entities", "matched": len(chosen), "complete": False, "narrow_by": narrow,
         "groups": [{**_group(ms), "count": len(ms)} for ms in groups]},
        {"level": "entities", "matched": len(chosen), "complete": False, "narrow_by": narrow},
    ]


def _group(members: list[Entity]) -> Body:
    """One area's entities of one domain and kind (`device_class`, left out when they have none)."""
    kind = _device_class(members[0])
    return {"area": members[0].area, "domain": members[0].domain, **({"kind": kind} if kind else {})}


def _nothing(entities: tuple[Entity, ...], query: Query, selection: Selection, config: HouseStateConfig) -> Body:
    """Matched nothing: which filter failed, and for a name, the whole house as the first house form that fits beside
    it, so the answer settles what there is without another call."""
    body: Body = {"level": query.level, "matched": 0, "complete": True}
    if selection.unknown_area:
        body["known_areas"] = [_label(ms) for ms in _by(entities, _area_key).values()]
    if selection.unknown_domain:
        body["known_domains"] = sorted({e.domain for e in entities})
    if selection.unmatched_words:
        body["unmatched_words"] = list(selection.unmatched_words)
    if query.name is not None and entities and not (selection.unknown_area or selection.unknown_domain):
        houses = _house(entities, config)
        fits = [h for h in houses if len(_json({**body, "house": h})) <= config.max_chars]
        body["house"] = (fits or houses[-1:])[0]
    return body


def _entity(e: Entity, zone: tzinfo | None) -> Body:
    body: Body = {"names": ", ".join(e.names), "domain": e.domain, "area": e.area, "state": e.state}
    if zone is not None and e.changed is not None:
        body["changed"] = stamp(e.changed, zone)
    if e.attributes:
        body["attributes"] = dict(e.attributes)
    return body


def _area_summary(members: list[Entity], config: HouseStateConfig) -> str:
    return "; ".join(_summary(d, ms, config) for d, ms in _by(members, lambda e: e.domain).items())


def _summary(domain: str, members: list[Entity], config: HouseStateConfig) -> str:
    """One kind in one place: each named with its state when there are few, else counted by state, else by
    `device_class`, else just counted."""
    if len(members) <= config.list_at_most:
        return f"{domain}: " + "; ".join(_inline(e, config) for e in members)
    tally = _tally((e.state for e in members), config.tally_at_most)
    if tally is None:
        tally = _tally((_device_class(e) or "unclassified" for e in members), config.tally_at_most)
    if tally is None:
        tally = f"{len({e.state for e in members})} different states"
    return f"{domain} {len(members)} ({tally})"


def _inline(e: Entity, config: HouseStateConfig) -> str:
    unit = e.attributes.get("unit_of_measurement")
    text = f"{e.names[0]} {e.state}" + (f" {unit}" if unit is not None else "")
    extras = [f"{a} {e.attributes[a]}" for a in config.summary_attributes if e.attributes.get(a) is not None]
    return ", ".join([text, *extras])


def _tally(values: Iterable[str], at_most: int) -> str | None:
    counts = Counter(values)
    if len(counts) > at_most:
        return None
    return ", ".join(f"{v} {n}" for v, n in sorted(counts.items(), key=lambda vn: (-vn[1], vn[0])))


def _device_class(e: Entity) -> str | None:
    value = e.attributes.get("device_class")
    return value if isinstance(value, str) and value else None


def _by[K](entities: Iterable[Entity], key: Callable[[Entity], K]) -> dict[K, list[Entity]]:
    """The entities grouped by `key`, the groups in key order, each group in the order given."""
    groups: dict[K, list[Entity]] = {}
    for e in entities:
        groups.setdefault(key(e), []).append(e)
    return dict(sorted(groups.items(), key=lambda kv: _sort_key(kv[0])))


def _sort_key(key: object) -> str:
    return json.dumps(key, ensure_ascii=False)


def _area_key(e: Entity) -> tuple[bool, str]:
    return (not e.areas, e.area.casefold())


def _label(members: list[Entity]) -> str:
    return members[0].area


def _json(body: Body) -> str:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)
