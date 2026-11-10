"""Pieces of the household-money blind tests: two households (Willow with Alana and Elodie, another with Mia), a
conversation in each, and a real PostgresMemory over a pool."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
from ashley.db.pool import PoolDatabase
from ashley.hearing import Visibility
from ashley.memory.memory import Memory
from ashley.memory.model import Add, Asker, Kind, NewFact
from ashley.memory.postgres import PostgresMemory
from ashley.people import admin
from contract.conversations_support import scalar

AT = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
TEXT = "The household budget for groceries is four hundred dollars"
QUERY = "grocery budget"


@dataclass(frozen=True)
class Home:
    url: str
    id: int
    alana: int
    elodie: int
    talk: int
    other: int
    mia: int
    other_talk: int

    def asker(self, speaker: int | None, owner_only: bool, household: int | None = None) -> Asker:
        return Asker(self.id if household is None else household, speaker, owner_only, AT)

    def row(self, fact_id: int) -> tuple[int | None, int | None, str, str]:
        """(about_id, owner_id, visibility, kind) of a stored fact."""
        with psycopg.connect(self.url) as conn:
            got = conn.execute("SELECT about_id, owner_id, visibility, kind FROM facts WHERE id = %s",
                               (fact_id,)).fetchone()
        assert got is not None
        return got[0], got[1], str(got[2]), str(got[3])

    def raw(self, text: str, owner: int | None, visibility: str, about: int | None = None, kind: str = "finance",
            standing: bool = False) -> int:
        return int(scalar(self.url, "INSERT INTO facts (household_id, about_id, owner_id, visibility, "
                                    "visibility_stated, kind, standing, text, source_conversation_id, valid_from) "
                                    "VALUES (%s, %s, %s, %s, false, %s, %s, %s, %s, now()) RETURNING id",
                          (self.id, about, owner, visibility, kind, standing, text, self.talk)))


def make_home(url: str) -> Home:
    with psycopg.connect(url) as conn:
        hid = admin.add_household(conn, "Willow", "America/Denver")
        alana, elodie = admin.add_person(conn, hid, "Alana"), admin.add_person(conn, hid, "Elodie")
        other = admin.add_household(conn, "Elsewhere", "America/Denver")
        mia = admin.add_person(conn, other, "Mia")
    talk = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (hid,)))
    other_talk = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                            (other,)))
    return Home(url, hid, alana, elodie, talk, other, mia, other_talk)


@asynccontextmanager
async def memory(url: str) -> AsyncGenerator[Memory]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresMemory(db)
    finally:
        await db.close()


def money(about: int | None = None, owner: int | None = None, visibility: Visibility = "private", stated: bool = False,
          kind: Kind = "finance", text: str = TEXT) -> Add:
    return Add(NewFact(about, owner, visibility, stated, kind, False, text))
