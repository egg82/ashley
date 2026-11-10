"""Who is who, as values. Every id is a Postgres identity."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Person:
    id: int
    household_id: int
    name: str


@dataclass(frozen=True)
class Household:
    """`timezone` is an IANA name (`America/Denver`): the household's local time, for anything said about the time of
    day. `profile` is what she always knows about the household, as prose for the system prompt (who lives there,
    pronouns, pets, how calendars and lists are named); empty when none is set. Standing facts in memory replace
    it. `people` are ordered by id."""

    id: int
    name: str
    timezone: str
    profile: str
    people: tuple[Person, ...]


@dataclass(frozen=True)
class Account:
    """One identity a person has somewhere else, mapped to them explicitly, never guessed: `system` names where
    (`home_assistant`, `discord`, `authentik`) and `external_id` is that system's own id for them
    (`person.alana`, a Discord user id). One person may have several; an external id maps to at most one person.
    `handle` is the account's name on that system when its person linked it themselves (a Discord username), shown
    to that person only and never matched; empty when the admin mapped it."""

    id: int
    household_id: int
    person_id: int
    system: str
    external_id: str
    handle: str = ""
