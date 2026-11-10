"""Which of the house's entities one `house_state` call asks about. Its arguments are structured (`area`, `domain`,
`name`) and are matched against the entities' own fields, never against anything else she said:

- `area`: one of the area's names or aliases, or `NO_AREA`;
- `domain`: the entity's domain (`light`, `media_player`);
- `name`: every word must be a word of the entity's names or aliases, its area's, its domain or its `device_class`.

Words compare case-blind, `_` as a space, a trailing "s" or "es" ignored, and a word of four letters or more also
matches a longer word it begins ("temp", "temperature")."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .house_entities import NO_AREA, Entity

Level = Literal["house", "area", "entities"]
ARGUMENTS = ("area", "domain", "name")
_WORD = re.compile(r"[^\W_]+")
_PREFIX_AT = 4


@dataclass(frozen=True)
class Query:
    area: str | None = None
    domain: str | None = None
    name: str | None = None

    @property
    def level(self) -> Level:
        if self.domain is None and self.name is None:
            return "house" if self.area is None else "area"
        return "entities"

    def given(self) -> tuple[str, ...]:
        return tuple(a for a in ARGUMENTS if getattr(self, a) is not None)


@dataclass(frozen=True)
class Selection:
    """The entities the query matched, in the order given. When none did, which filter failed: an `area` or `domain`
    that names nothing in the house, or the `name` words that are no word of any entity at all."""

    entities: tuple[Entity, ...]
    unknown_area: bool = False
    unknown_domain: bool = False
    unmatched_words: tuple[str, ...] = ()


def query_of(arguments: Mapping[str, object]) -> Query:
    """The Query a call's arguments ask for; an empty or blank string is the argument left out. Raises ValueError,
    naming only argument names, for an unknown argument or one that is not a string."""
    unknown = sorted(k for k in arguments if k not in ARGUMENTS)
    if unknown:
        raise ValueError(f"house_state takes only {', '.join(ARGUMENTS)}; not {', '.join(unknown)}")
    values: dict[str, str | None] = {}
    for key in ARGUMENTS:
        value = arguments.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"house_state's {key} is a string")
        values[key] = value.strip() if value is not None and value.strip() else None
    return Query(**values)


def select(entities: tuple[Entity, ...], query: Query) -> Selection:
    """The entities matching every argument the query gives."""
    chosen = entities
    if query.area is not None:
        chosen = tuple(e for e in chosen if _in_area(e, query.area))
        if not chosen:
            return Selection((), unknown_area=True)
    if query.domain is not None:
        chosen = tuple(e for e in chosen if _same_words(_words(e.domain), _words(query.domain)))
        if not chosen:
            return Selection((), unknown_domain=not any(_same_words(_words(e.domain), _words(query.domain))
                                                        for e in entities))
    if query.name is not None:
        wanted = _words(query.name)
        chosen = tuple(e for e in chosen if all(_matches_any(w, _vocabulary(e)) for w in wanted))
        if not chosen:
            every = [word for e in entities for word in _vocabulary(e)]
            return Selection((), unmatched_words=tuple(w for w in wanted if not _matches_any(w, every)))
    return Selection(chosen)


def _in_area(entity: Entity, area: str) -> bool:
    if area.casefold() == NO_AREA.casefold():
        return not entity.areas
    return any(_same_words(_words(a), _words(area)) for a in entity.areas)


def _vocabulary(entity: Entity) -> list[str]:
    device_class = entity.attributes.get("device_class")
    texts = [*entity.names, *entity.areas, entity.domain, device_class if isinstance(device_class, str) else ""]
    return [word for text in texts for word in _words(text)]


def _words(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(text.casefold()))


def _same_words(have: tuple[str, ...], want: tuple[str, ...]) -> bool:
    return len(have) == len(want) and all(_same(h, w) for h, w in zip(have, want, strict=True))


def _matches_any(word: str, vocabulary: Iterable[str]) -> bool:
    return any(_same(have, word) or (len(word) >= _PREFIX_AT and have.startswith(word)) for have in vocabulary)


def _same(have: str, want: str) -> bool:
    return have == want or any(have + end == want or want + end == have for end in ("s", "es"))


def words_match(wanted: str, texts: Iterable[str]) -> bool:
    """Whether every word of `wanted` is a word of one of `texts`, as a `name` argument matches."""
    vocabulary = [word for text in texts for word in _words(text)]
    return all(_matches_any(w, vocabulary) for w in _words(wanted))


def same_text(have: str, want: str) -> bool:
    """Whether the two are the same words, as an `area` or `domain` argument matches."""
    return _same_words(_words(have), _words(want))
