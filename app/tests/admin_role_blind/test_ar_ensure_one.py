"""App mode, no admin: the next sign-in by anyone makes the earliest person of the first household an admin, not
necessarily the person signing in, and two sign-ins at once make exactly one."""

import asyncio

from admin_role_blind_support import (PUBLIC, MultiIdp, World, admin_ids, app_mode as app_mode, build,
                                      idp as idp, me, set_admin, sign_in, world as world)
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient
import pytest


def test_app_mode_with_no_admin_the_next_sign_in_makes_the_lowest_id_person_admin_not_the_signer(
        app_mode: TestClient, db_url: str, world: World, idp: MultiIdp) -> None:
    assert admin_ids(db_url) == []
    assert sign_in(app_mode, idp, world.sub(world.ivy)).status_code == 302
    assert admin_ids(db_url) == [world.alana]
    assert me(app_mode)["admin"] is False


def test_app_mode_the_earliest_person_signing_in_is_made_admin(app_mode: TestClient, db_url: str, world: World,
                                                              idp: MultiIdp) -> None:
    sign_in(app_mode, idp, world.sub(world.alana))
    assert admin_ids(db_url) == [world.alana]
    assert me(app_mode)["admin"] is True


def test_app_mode_a_sign_in_by_another_household_makes_the_first_household_s_earliest_admin(
        app_mode: TestClient, db_url: str, world: World, idp: MultiIdp) -> None:
    sign_in(app_mode, idp, world.sub(world.kim))
    assert admin_ids(db_url) == [world.alana]
    assert me(app_mode)["admin"] is False


def test_app_mode_with_an_admin_a_sign_in_changes_nobody(app_mode: TestClient, db_url: str, world: World,
                                                         idp: MultiIdp) -> None:
    set_admin(db_url, world.ivy)
    sign_in(app_mode, idp, world.sub(world.sam))
    sign_in(app_mode, idp, world.sub(world.alana))
    assert admin_ids(db_url) == [world.ivy]


def test_app_mode_after_the_last_admin_is_gone_the_next_sign_in_makes_one_again(app_mode: TestClient, db_url: str,
                                                                               world: World, idp: MultiIdp) -> None:
    set_admin(db_url, world.sam)
    sign_in(app_mode, idp, world.sub(world.ivy))
    assert admin_ids(db_url) == [world.sam]
    set_admin(db_url, world.sam, False)
    sign_in(app_mode, idp, world.sub(world.ivy))
    assert admin_ids(db_url) == [world.alana]


def test_app_mode_two_sign_ins_at_once_leave_exactly_one_new_admin(db_url: str, world: World, idp: MultiIdp,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    app = build(db_url, idp, monkeypatch)

    async def one_round(subs: tuple[str, str]) -> None:
        async with AsyncClient(transport=ASGITransport(app), base_url=PUBLIC) as a, \
                AsyncClient(transport=ASGITransport(app), base_url=PUBLIC) as b:
            started = await asyncio.gather(a.get("/api/auth/signin"), b.get("/api/auth/signin"))
            grants = [idp.authorize_as(s.headers["location"], sub) for s, sub in zip(started, subs)]
            done = await asyncio.gather(*(c.get("/api/auth/callback", params={"code": code, "state": state})
                                          for c, (code, state) in zip((a, b), grants)))
            assert [d.status_code for d in done] == [302, 302]

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            for _ in range(6):
                await one_round((world.sub(world.ivy), world.sub(world.sam)))
                await asyncio.to_thread(_check_and_reset, db_url, world)

    asyncio.run(scenario())


def _check_and_reset(url: str, world: World) -> None:
    got = admin_ids(url)
    assert got == [world.alana], f"two sign-ins at once must make exactly one admin, the earliest person: {got}"
    set_admin(url, world.alana, False)
