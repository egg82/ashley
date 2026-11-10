"""Helpers for the blind standing-facts tests: facts built by keyword (so the field order is not assumed), a household
with the cast the visibility matrix needs, and the Postgres rows read back."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ashley.memory.model import Add, Asker, Fact, Kind, NewFact, Visibility
from ashley.memory.postgres import PostgresMemory

from conversations_support import household, person, scalar
from memory_support import conversation

AT = datetime(2026, 3, 1, tzinfo=UTC)
LATER = AT + timedelta(days=2)


def new(owner: int | None, text: str, *, standing: bool = True, kind: Kind = "other",
        visibility: Visibility = "shared", stated: bool = True) -> NewFact:
    return NewFact(about_id=owner, owner_id=owner, visibility=visibility, visibility_stated=stated, kind=kind,
                   standing=standing, text=text)


def stored_fact(fact_id: int, text: str, *, standing: bool, kind: Kind = "other", visibility: Visibility = "shared",
                household_id: int = 5) -> Fact:
    return Fact(id=fact_id, household_id=household_id, about_id=None, owner_id=None, visibility=visibility,
                kind=kind, standing=standing, text=text, source_conversation_id=1, valid_from=AT, valid_to=None,
                superseded_by=None)


def column(url: str, fact_id: int, name: str) -> object:
    return scalar(url, f"SELECT {name} FROM facts WHERE id = %s", (fact_id,))


@dataclass(frozen=True)
class Cast:
    home: int
    alana: int
    elodie: int
    talk: int
    other_home: int
    zed: int
    foreign_talk: int


def seated(url: str) -> Cast:
    home, other = household(url), household(url, "other")
    alana, elodie, zed = person(url, home, "alana"), person(url, home, "elodie"), person(url, other, "zed")
    return Cast(home, alana, elodie, conversation(url, home), other, zed, conversation(url, other))


async def add_all(memory: PostgresMemory, home: int, talk: int, facts: list[NewFact]) -> tuple[int, ...]:
    return await memory.apply(home, talk, [Add(f) for f in facts], AT)


def asker(home: int, speaker: int | None = None, owner_only: bool = False) -> Asker:
    return Asker(home, speaker, owner_only, LATER)
