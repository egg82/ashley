"""PostgresSessions over a real database: a sign-in in flight is taken once and only in time; a session opens only for
an account mapped to a person, ends at its expiry, when idle, when closed or when its account goes; its use is written
at most every `touch_minutes`; refused accounts are kept for the admin and swept after their retention."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace

import psycopg
import pytest
from ashley.db.pool import PoolDatabase
from ashley.people import admin
from ashley.people.model import Person
from ashley.signin import policy as signin_policy
from ashley.signin.__main__ import main
from ashley.signin.model import Pending
from ashley.signin.postgres import PostgresSessions
from ashley.signin.sessions import SessionsUnavailable
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import run, scalar
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

POLICY = signin_policy.load()
PENDING = Pending("verifier-1", "nonce-1", "/memory")


def household(url: str) -> tuple[int, int, int]:
    """(household, person, account) with the person's OIDC account `sub-alana`."""
    with psycopg.connect(url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        pid = admin.add_person(conn, hid, "Alana")
        aid = admin.add_account(conn, pid, "authentik", "sub-alana")
    return hid, pid, aid


def execute(url: str, query: str, params: tuple[object, ...] = ()) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(query.encode(), params)


@asynccontextmanager
async def sessions(url: str, **policy: int) -> AsyncGenerator[PostgresSessions]:
    db = PoolDatabase(url)
    await db.open()
    try:
        yield PostgresSessions(db, replace(POLICY, **policy))
    finally:
        await db.close()


def test_a_sign_in_in_flight_is_taken_once(db_url: str) -> None:
    async def scenario() -> None:
        async with sessions(db_url) as s:
            assert await s.begin("state-1", PENDING) is True
            assert await s.take("state-2") is None
            assert await s.take("state-1") == PENDING
            assert await s.take("state-1") is None

    run(scenario())


def test_a_sign_in_past_its_minutes_is_not_taken_and_is_swept(db_url: str) -> None:
    async def scenario() -> None:
        async with sessions(db_url) as s:
            await s.begin("old", PENDING)
            await s.begin("late", PENDING)
            execute(db_url, "UPDATE signin_pending SET created_at = now() - interval '11 minutes'")
            assert await s.take("late") is None
            await s.begin("new", PENDING)
            assert scalar(db_url, "SELECT count(*) FROM signin_pending") == 1

    run(scenario())


def test_no_more_sign_ins_are_stored_than_the_policy_allows(db_url: str) -> None:
    async def scenario() -> None:
        async with sessions(db_url, max_pending=2) as s:
            assert [await s.begin(f"s{i}", PENDING) for i in range(3)] == [True, True, False]
            assert await s.take("s2") is None

    run(scenario())


def test_only_a_mapped_account_opens_a_session_and_its_token_finds_the_person(db_url: str) -> None:
    hid, pid, _ = household(db_url)

    async def scenario() -> None:
        async with sessions(db_url) as s:
            assert await s.open("authentik", "sub-stranger") is None
            assert await s.open("discord", "sub-alana") is None
            opened = await s.open("authentik", "sub-alana")
            assert opened is not None and opened.signed_in.person == Person(pid, hid, "Alana")
            assert await s.find(opened.token) == opened.signed_in
            assert await s.find(opened.token + "x") is None
            assert await s.find("") is None

    run(scenario())
    stored = scalar(db_url, "SELECT encode(token_sha256, 'hex') FROM sessions")
    assert len(stored) == 64, "only the hash is stored"


def test_a_session_ends_at_its_expiry_or_when_idle(db_url: str) -> None:
    household(db_url)

    async def scenario() -> None:
        async with sessions(db_url) as s:
            expired, idle, live = [await s.open("authentik", "sub-alana") for _ in range(3)]
            assert expired and idle and live
            execute(db_url, "UPDATE sessions SET expires_at = now() - interval '1 second' WHERE id = %s",
                    (expired.signed_in.session_id,))
            execute(db_url, "UPDATE sessions SET last_seen_at = now() - make_interval(days => %s) - interval '1 minute' "
                    "WHERE id = %s", (POLICY.idle_days, idle.signed_in.session_id))
            assert await s.find(expired.token) is None
            assert await s.find(idle.token) is None
            assert await s.find(live.token) == live.signed_in
            await s.open("authentik", "sub-alana")
            assert scalar(db_url, "SELECT count(*) FROM sessions") == 2, "the dead two were swept"

    run(scenario())


def test_a_session_is_opened_for_session_days(db_url: str) -> None:
    household(db_url)

    async def scenario() -> None:
        async with sessions(db_url) as s:
            assert await s.open("authentik", "sub-alana")

    run(scenario())
    days = scalar(db_url, "SELECT extract(epoch FROM expires_at - created_at) / 86400 FROM sessions")
    assert round(float(days), 3) == POLICY.session_days


def test_use_is_written_only_after_touch_minutes(db_url: str) -> None:
    household(db_url)

    async def scenario() -> None:
        async with sessions(db_url) as s:
            opened = await s.open("authentik", "sub-alana")
            assert opened
            execute(db_url, "UPDATE sessions SET last_seen_at = now() - make_interval(mins => %s) + interval '1 minute'",
                    (POLICY.touch_minutes,))
            before = scalar(db_url, "SELECT last_seen_at FROM sessions")
            await s.find(opened.token)
            assert scalar(db_url, "SELECT last_seen_at FROM sessions") == before
            execute(db_url, "UPDATE sessions SET last_seen_at = now() - make_interval(mins => %s) - interval '1 minute'",
                    (POLICY.touch_minutes,))
            await s.find(opened.token)
            assert scalar(db_url, "SELECT now() - last_seen_at < interval '1 minute' FROM sessions") is True

    run(scenario())


def test_close_ends_only_that_session_and_says_whose_it_was(db_url: str) -> None:
    hid, pid, _ = household(db_url)

    async def scenario() -> None:
        async with sessions(db_url) as s:
            one, two = await s.open("authentik", "sub-alana"), await s.open("authentik", "sub-alana")
            assert one and two
            ended = await s.close(one.token)
            assert ended == one.signed_in and one.signed_in.person == Person(pid, hid, "Alana")
            assert await s.close(one.token) is None
            assert await s.find(one.token) is None
            assert await s.find(two.token) == two.signed_in

    run(scenario())


def test_removing_the_account_ends_its_sessions(db_url: str) -> None:
    _, _, aid = household(db_url)

    async def scenario() -> None:
        async with sessions(db_url) as s:
            opened = await s.open("authentik", "sub-alana")
            assert opened
            execute(db_url, "DELETE FROM accounts WHERE id = %s", (aid,))
            assert await s.find(opened.token) is None

    run(scenario())


def test_a_refused_account_is_listed_until_mapped_or_past_retention(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    _, pid, _ = household(db_url)

    async def scenario() -> None:
        async with sessions(db_url) as s:
            await s.refused("authentik", "sub-sam", "sam")
            await s.refused("authentik", "sub-sam", "sam.renamed")
            await s.refused("authentik", "sub-old", "old")
            execute(db_url, "UPDATE signin_unmapped SET last_seen_at = now() - make_interval(days => %s) "
                    "- interval '1 hour' WHERE external_id = 'sub-old'", (POLICY.unmapped_retention_days,))
            await s.refused("authentik", "sub-kim", "kim")

    run(scenario())
    monkeypatch.setenv("DATABASE_URL", db_url)
    assert main(["unmapped"]) == 0
    listed = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert [(row[0], row[2]) for row in listed] == [("sub-kim", "kim"), ("sub-sam", "sam.renamed")]
    assert all(len(row[1]) == 12 for row in listed)
    with psycopg.connect(db_url) as conn:
        admin.add_account(conn, pid, "authentik", "sub-kim")
    assert main(["unmapped"]) == 0
    assert [line.split("\t")[0] for line in capsys.readouterr().out.splitlines()] == ["sub-sam"]


def test_an_unreachable_database_is_sessions_unavailable() -> None:
    async def scenario() -> None:
        async with sessions(unreachable_conninfo()) as s:
            with pytest.raises(SessionsUnavailable):
                await s.find("anything")

    run(scenario())
