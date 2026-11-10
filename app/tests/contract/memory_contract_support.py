"""Helpers for the blind memory-page contract tests: two households (A and B in one, C in the other), each person
signed in to one app over a real database, facts planted through `Memory.apply`, and raw reads of the `facts` table.
The contract is `ashley.api.memory`'s docstrings, `openapi.json` and `decisions.md`, "People see, correct and forget
what she knows of them"."""

import asyncio
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from ashley.memory.model import Add, Kind, NewFact, Op, Update, Visibility
from conversations_support import household, person, scalar
from memory_support import conversation, pool, say
from ashley.memory.postgres import PostgresMemory
from people_support import account
from signin_contract_support import SITE, Browser, browser

WRITE = {"Origin": SITE}


@dataclass
class Cast:
    """Who is who: ids by name, and the cookies of each person's signed-in session."""

    url: str
    web: Browser
    hh: dict[str, int]
    who: dict[str, int]
    cookies: dict[str, dict[str, str]]

    def as_(self, name: str | None) -> Browser:
        """The browser, signed in as `name` (or no one)."""
        self.web.client.cookies.clear()
        for key, value in ({} if name is None else self.cookies[name]).items():
            self.web.client.cookies.set(key, value, domain="ashley.test")
        return self.web

    def get(self, name: str | None, path: str = "/api/memory/facts") -> Any:
        return self.as_(name).client.get(path)

    def listed(self, name: str) -> list[dict[str, Any]]:
        r = self.get(name)
        assert r.status_code == 200, r.text
        return list(r.json()["items"])

    def ids(self, name: str) -> set[int]:
        return {f["id"] for f in self.listed(name)}

    def correct(self, name: str | None, fact_id: int, body: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None, **kw: Any) -> Any:
        sent = {"text": "corrected"} if body is None else body
        return self.as_(name).client.post(f"/api/memory/facts/{fact_id}/corrections", json=sent,
                                          headers=WRITE if headers is None else headers, **kw)

    def forget(self, name: str | None, fact_id: int, headers: dict[str, str] | None = None) -> Any:
        return self.as_(name).client.delete(f"/api/memory/facts/{fact_id}",
                                            headers=WRITE if headers is None else headers)


@contextmanager
def household_cast(url: str) -> Generator[Cast]:
    """A and B in `home`, C in `other`, each with an OIDC account, all signed in."""
    hh = {"home": household(url, "home"), "other": household(url, "other")}
    who = {"A": person(url, hh["home"], "A"), "B": person(url, hh["home"], "B"), "C": person(url, hh["other"], "C")}
    with browser(url) as web:
        cookies: dict[str, dict[str, str]] = {}
        for name, home in (("A", "home"), ("B", "home"), ("C", "other")):
            account(url, hh[home], who[name], "authentik", f"sub-{name}")
            web.fake.sub = f"sub-{name}"
            web.client.cookies.clear()
            assert web.signin().status_code == 302
            cookies[name] = web.session_cookies()
            assert cookies[name], "sign-in left no session cookie"
        yield Cast(url, web, hh, who, cookies)


def new_fact(about: int | None, owner: int | None, text: str, visibility: Visibility = "shared", kind: Kind = "other",
             standing: bool = False) -> NewFact:
    return NewFact(about_id=about, owner_id=owner, visibility=visibility,
                   visibility_stated=True, kind=kind, standing=standing, text=text)


def apply(url: str, household_id: int, conversation_id: int, *ops: Op) -> tuple[int, ...]:
    async def run() -> tuple[int, ...]:
        async with pool(url) as db:
            return await PostgresMemory(db).apply(household_id, conversation_id, list(ops), datetime.now(UTC))
    return asyncio.run(run())


def plant(url: str, household_id: int, conversation_id: int, fact: NewFact) -> int:
    return apply(url, household_id, conversation_id, Add(fact))[0]


def supersede(url: str, household_id: int, conversation_id: int, old: int, fact: NewFact) -> int:
    return apply(url, household_id, conversation_id, Update(old, fact))[0]


def talk(url: str, household_id: int, speaker: int, *turns: str, kind: str = "chat") -> int:
    """A conversation the speaker took part in, with these turns."""
    cid = conversation(url, household_id, kind)
    scalar(url, "INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                "VALUES (%s, %s, %s) RETURNING conversation_id", (cid, household_id, speaker))
    say(url, cid, *turns, speaker=speaker)
    return cid


def rows(url: str, ids: Sequence[int] | None = None) -> list[tuple[Any, ...]]:
    """(id, text, valid_to is null, superseded_by) of the stored facts, optionally only these ids."""
    with psycopg.connect(url) as conn:
        q = "SELECT id, text, valid_to IS NULL, superseded_by FROM facts"
        if ids is None:
            return conn.execute((q + " ORDER BY id").encode()).fetchall()
        return conn.execute((q + " WHERE id = ANY(%s) ORDER BY id").encode(), (list(ids),)).fetchall()
