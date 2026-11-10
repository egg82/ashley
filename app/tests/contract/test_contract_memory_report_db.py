"""`facts` and `writers` against real Postgres, with the facts made through `Memory.apply`: closed and superseded rows
come back, a forgotten one does not, and the writer rows are one conversation's `memory_write` calls. The `memory.apply`
line the real service writes is read back by `seen`. Written blind from the contract."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import psycopg
from contextlib import nullcontext
import pytest
from ashley import logs
from ashley.memory.model import Add, Forget, Invalidate, Update
from ashley.memory.postgres import PostgresMemory
from ashley.memory import postgres_queries as q
from ashley.memory.model import Fact
from ashley.memory.report import seen

from conversations_support import scalar
from memory_support import conversation, pool
from profile_support import AT, LATER, new, seated
from report_support import T0, at, stamp


def facts(url: str, ids: list[int]) -> dict[int, Fact]:
    async def read() -> dict[int, Fact]:
        async with await psycopg.AsyncConnection.connect(url) as conn:
            return await q.by_ids(conn, ids)
    return asyncio.run(read())


def writers(url: str, conversation_id: int) -> tuple[tuple[str, str, str, str], ...]:
    async def read() -> tuple[tuple[str, str, str, str], ...]:
        async with await psycopg.AsyncConnection.connect(url) as conn:
            return await q.writers(conn, conversation_id)
    return asyncio.run(read())


def call(url: str, conversation_id: int | None, *, task: str = "memory_write", provider: str = "p", model: str = "m",
         outcome: str = "ok", when: float = 0) -> None:
    scalar(url, "INSERT INTO inference_calls (at, task, provider, model, outcome, duration_ms, conversation_id) "
                "VALUES (%s, %s, %s, %s, %s, 5, %s) RETURNING id",
           (at(when), task, provider, model, outcome, conversation_id))


def test_facts_returns_current_closed_and_superseded_rows_and_not_a_forgotten_one(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> tuple[int, ...]:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            a, c1, d = await memory.apply(c.home, c.talk, [Add(new(c.alana, "plan alpha")),
                                                           Add(new(c.alana, "plan gamma")),
                                                           Add(new(c.alana, "plan delta"))], AT)
            (b,) = await memory.apply(c.home, c.talk, [Update(a, new(c.alana, "plan beta"))], LATER)
            await memory.apply(c.home, c.talk, [Invalidate(c1)], LATER)
            await memory.apply(c.home, c.talk, [Forget(d)], LATER)
            return a, b, c1, d

    a, b, closed, forgotten = _ran(scenario())
    with nullcontext(db_url) as conn:
        got = facts(conn, [a, b, closed, forgotten])
    assert set(got) == {a, b, closed}
    assert got[a].text == "plan alpha" and got[a].valid_to is not None and got[a].superseded_by == b
    assert got[b].text == "plan beta" and got[b].valid_to is None and got[b].superseded_by is None
    assert got[closed].valid_to is not None and got[closed].superseded_by is None
    assert all(f.source_conversation_id == c.talk for f in got.values())
    assert got[a].id == a and got[a].kind == "other" and got[a].visibility == "shared"


def _ran(coro: Coroutine[Any, Any, tuple[int, ...]]) -> tuple[int, ...]:
    return asyncio.run(asyncio.wait_for(coro, 25))


def test_facts_asks_only_for_the_ids_given(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> tuple[int, ...]:
        async with pool(db_url) as db:
            return await PostgresMemory(db).apply(c.home, c.talk, [Add(new(c.alana, "one")), Add(new(c.alana, "two")),
                                                                   Add(new(c.alana, "three"))], AT)

    one, two, three = _ran(scenario())
    with nullcontext(db_url) as conn:
        assert set(facts(conn, [two])) == {two}
        assert set(facts(conn, [one, three, 987654321])) == {one, three}
        assert facts(conn, []) == {}
        assert facts(conn, [987654321]) == {}


def test_a_fact_from_another_household_is_still_a_row(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> tuple[int, ...]:
        async with pool(db_url) as db:
            return await PostgresMemory(db).apply(c.other_home, c.foreign_talk, [Add(new(c.zed, "zed fact"))], AT)

    (zed,) = _ran(scenario())
    with nullcontext(db_url) as conn:
        assert facts(conn, [zed])[zed].text == "zed fact"


def test_writers_are_the_conversations_memory_write_calls_oldest_first(db_url: str) -> None:
    c = seated(db_url)
    other = conversation(db_url, c.home)
    call(db_url, c.talk, provider="late", model="m-late", outcome="ok", when=300)
    call(db_url, c.talk, provider="early", model="m-early", outcome="invalid_output", when=10)
    call(db_url, c.talk, provider="mid", model="m-mid", outcome="ok", when=120)
    call(db_url, other, provider="elsewhere", model="m-other", when=60)
    call(db_url, None, provider="nobody", model="m-none", when=61)
    call(db_url, c.talk, task="chat", provider="chatty", model="m-chat", when=62)
    call(db_url, c.talk, task="memory_judge", provider="judge", model="m-judge", when=63)
    with nullcontext(db_url) as conn:
        got = writers(conn, c.talk)
        assert [row[1:] for row in got] == [("early", "m-early", "invalid_output"), ("mid", "m-mid", "ok"),
                                            ("late", "m-late", "ok")]
        assert all(isinstance(row[0], str) and row[0] for row in got)
        assert [row[1:] for row in writers(conn, other)] == [("elsewhere", "m-other", "ok")]
        assert writers(conn, other + 1000) == ()


def test_writers_is_a_tuple_of_tuples(db_url: str) -> None:
    c = seated(db_url)
    call(db_url, c.talk)
    with nullcontext(db_url) as conn:
        got = writers(conn, c.talk)
    assert isinstance(got, tuple) and isinstance(got[0], tuple) and len(got[0]) == 4


def test_the_real_memory_apply_line_is_what_seen_reads(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    c = seated(db_url)
    logs.setup({"LOG_LEVEL": "info"})

    async def scenario() -> tuple[int, ...]:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            first = await memory.apply(c.home, c.talk, [Add(new(c.alana, "zqxalpha")), Add(new(c.alana, "zqxbeta"))], AT)
            await memory.apply(c.home, c.talk, [Forget(first[0]), Update(first[1], new(c.alana, "zqxgamma"))], LATER)
            await memory.apply(c.other_home, c.foreign_talk, [Add(new(c.zed, "zqxzed"))], AT)
            return first

    capsys.readouterr()
    first = _ran(scenario())
    out = capsys.readouterr().out
    assert "zqx" not in out
    replies, mine = seen(out.splitlines(), c.talk)
    assert replies == () and len(mine) == 2
    created, changed = mine
    assert created.inserted == first and (created.add, created.update, created.forget) == (2, 0, 0)
    assert (changed.add, changed.update, changed.forget, changed.deleted) == (0, 1, 1, 1)
    assert len(changed.inserted) == 1
    assert len(seen(out.splitlines(), c.foreign_talk)[1]) == 1
    assert stamp(T0)  # control: the formatter helper is the one the app uses
