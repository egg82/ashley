"""The house's things as `house_entities.Entity` (what `house_query` matches and `house_render` summarises) and which of
them one call names. A call names things by `ids` (exact), or by `area`, `domain` and `name` as `house_query` matches
them; a `name` that matches more than one thing, none of them named exactly that, is ambiguous and acts on none."""

from collections.abc import Mapping
from dataclasses import dataclass

from ..home_assistant.house import State
from . import house_args as args
from .house_entities import Entity, Scalar
from .house_query import Query, select


def entity_of(state: State) -> Entity:
    """`state` in the form the matcher reads: its names (name, then aliases), its area's, and scalar attributes."""
    areas = () if state.area is None else (state.area, *state.area_aliases)
    return Entity((state.name, *state.aliases), state.domain, state.state, areas, _scalars(state.attributes), state.id,
                  state.featured, state.changed)


def _scalars(attributes: Mapping[str, object]) -> Mapping[str, Scalar]:
    return {k: v for k, v in attributes.items() if v is None or isinstance(v, str | int | float | bool)}


@dataclass(frozen=True)
class Targets:
    """The things a call names: their `ids`, or why none: `ambiguous` the names of the things a `name` fits equally,
    `unknown` that nothing fits."""

    ids: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    unknown: bool = False


def resolve(entities: tuple[Entity, ...], query: Query, ids: tuple[str, ...] = ()) -> Targets:
    """The things `query` and `ids` name. `ids` that are in the house are taken as given; one that is not makes the call
    `unknown`."""
    if ids:
        known = {e.id for e in entities}
        return Targets(ids) if all(i in known for i in ids) else Targets(unknown=True)
    if query.given() == ():
        return Targets()
    chosen = select(entities, query).entities
    if not chosen:
        return Targets(unknown=True)
    if query.name is not None and len(chosen) > 1:
        return _one_of(chosen, query.name)
    return Targets(tuple(e.id for e in chosen))


def named(states: tuple[Entity, ...], arguments: Mapping[str, object], action_domain: str) -> Targets:
    """The things a house call's `ids`, `name`, `area` and `domain` name; the action's own domain is assumed when the house
    has things in it. Raises ValueError as `house_args` does."""
    domain = args.text(arguments, "domain") or (action_domain if any(e.domain == action_domain for e in states) else None)
    query = Query(args.text(arguments, "area"), domain, args.text(arguments, "name"))
    return resolve(states, query, args.texts(arguments, "ids"))


def _one_of(chosen: tuple[Entity, ...], name: str) -> Targets:
    """The one thing `name` is, among several it fits: the one named exactly that, else the one the household lists
    when only one is listed, else ambiguous."""
    for pool in (chosen, tuple(e for e in chosen if e.featured)):
        exact = tuple(e for e in pool if _named(e, name))
        if len(exact) == 1:
            return Targets((exact[0].id,))
        if len(pool) == 1:
            return Targets((pool[0].id,))
    return Targets(ambiguous=tuple(sorted({e.names[0] for e in chosen})))


def _named(entity: Entity, name: str) -> bool:
    wanted = " ".join(name.casefold().split())
    return any(" ".join(n.casefold().split()) == wanted for n in entity.names)
