"""The language a household's `locale` names, for the places that listen in it and answer in it."""

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

from .. import services
from .people import People, PeopleUnavailable


@dataclass(frozen=True)
class Language:
    """`code` is the ISO 639-1 code speech-to-text takes (`de`); `name` is the language in English (`German`)."""

    code: str
    name: str


@cache
def _names() -> dict[str, str]:
    """The languages speech-to-text can be told, from `languages.json` beside this module."""
    return json.loads(resources.files("ashley.people").joinpath("languages.json").read_text())


def language_of(locale: str) -> Language | None:
    """The language of a BCP 47 `locale` (`de-DE` is German); None when it is not one speech-to-text takes, so the
    caller keeps its shipped default."""
    code = locale.split("-", 1)[0]
    name = _names().get(code)
    return None if name is None else Language(code, name)


async def language_for(household_id: int) -> Language | None:
    """The household's language; None (the shipped default) when people cannot be reached, there is no such household
    or its locale names no language."""
    try:
        household = await services.get(People).household(household_id)
    except PeopleUnavailable:
        return None
    return None if household is None else language_of(household.locale)
