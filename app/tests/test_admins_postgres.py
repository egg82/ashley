"""`Admins` in Postgres (`ashley.people.postgres_admins`), raced for real: two pools stand for two pods on two sites, and
every round fires its calls at once. Whenever no one is an admin exactly one call makes the earliest person of the first
household one; two admins revoking each other at once leave one of them; the last admin is never revoked."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from admin_role_support import Deployment, admins, deployment, set_admin
from ashley.db.pool import PoolDatabase
from ashley.people.admins import Admins, Outcome
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar

ROUNDS = 8
CALLS_PER_POD = 4


def raced[T](url: str, call: Callable[[Admins, int], Awaitable[T]],
             between: Callable[[], None] = lambda: None) -> list[list[T]]:
    """Each round's answers to `call(writer, i)` for `CALLS_PER_POD` writers on each of two pools, made at once;
    `between` runs after every round."""
    from ashley.people.postgres_admins import PostgresAdmins

    async def scenario() -> list[list[T]]:
        pods = [PoolDatabase(url), PoolDatabase(url)]
        for pod in pods:
            await pod.open()
        try:
            out: list[list[T]] = []
            for _ in range(ROUNDS):
                writers = [PostgresAdmins(pod) for pod in pods for _ in range(CALLS_PER_POD)]
                out.append(list(await asyncio.gather(*(call(w, i) for i, w in enumerate(writers)))))
                between()
            return out
        finally:
            for pod in pods:
                await pod.close()
    return asyncio.run(scenario())


def once[T](url: str, call: Callable[[Admins], Awaitable[T]]) -> T:
    from ashley.people.postgres_admins import PostgresAdmins

    async def scenario() -> T:
        pod = PoolDatabase(url)
        await pod.open()
        try:
            return await call(PostgresAdmins(pod))
        finally:
            await pod.close()
    return asyncio.run(scenario())


@pytest.fixture
def home(db_url: str) -> Deployment:
    return deployment(db_url)


def test_with_no_admin_racing_calls_make_exactly_one_and_always_the_earliest(home: Deployment) -> None:
    seen: list[list[int]] = []

    def between() -> None:
        seen.append(admins(home.url))
        set_admin(home.url, home.ana, False)
    answers = raced(home.url, lambda writer, _: writer.ensure_one(home.first), between)
    assert seen == [[home.ana]] * ROUNDS
    assert all([a for a in round_ if a is not None] == [home.ana] for round_ in answers), answers


def test_with_an_admin_no_call_makes_another(home: Deployment) -> None:
    set_admin(home.url, home.cy)
    answers = raced(home.url, lambda writer, _: writer.ensure_one(home.first))
    assert all(a is None for round_ in answers for a in round_)
    assert admins(home.url) == [home.cy]


def test_a_household_with_nobody_makes_no_admin(home: Deployment) -> None:
    empty = int(scalar(home.url, "INSERT INTO households (name) VALUES ('empty') RETURNING id"))
    assert once(home.url, lambda writer: writer.ensure_one(empty)) is None
    assert admins(home.url) == []


def test_two_admins_revoking_each_other_at_once_leave_one(home: Deployment) -> None:
    seen: list[list[int]] = []

    def between() -> None:
        seen.append(admins(home.url))
        set_admin(home.url, home.ana)
        set_admin(home.url, home.ben)
    between()
    seen.clear()

    def revoke(writer: Admins, i: int) -> Awaitable[Outcome]:
        me, them = (home.ana, home.ben) if i % 2 else (home.ben, home.ana)
        return writer.put(home.first, them, False, me)
    answers = raced(home.url, revoke, between)
    assert [len(round_) for round_ in seen] == [1] * ROUNDS, seen
    assert all("last_admin" in round_ for round_ in answers)


def test_put_grants_revokes_and_finds_no_one_outside_the_household(home: Deployment) -> None:
    set_admin(home.url, home.ana)

    async def calls(writer: Admins) -> list[Outcome]:
        return [await writer.put(home.first, home.ben, True, home.ana),
                await writer.put(home.first, home.ben, False, home.ana),
                await writer.put(home.first, home.kim, True, home.ana),
                await writer.put(home.first, home.ana, False, home.ana)]
    assert once(home.url, calls) == ["set", "set", "not_found", "last_admin"]
    assert admins(home.url) == [home.ana]
