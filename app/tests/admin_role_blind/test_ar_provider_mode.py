"""Provider mode (`ADMIN_GROUP` set): the provider's `groups` claim at each sign-in is the only source of admin,
granting and revoking, on every live session of the person; nothing is granted from the web; the app's own record
decides nothing while the group is set."""

import httpx2
import pytest
from admin_role_blind_support import (GROUP, ORIGIN, MultiIdp, World, admin_flags, admin_ids, as_, codes, idp as idp, me,
                                      people_listing, provider_mode as provider_mode, put_admin, running, session_for,
                                      set_admin, sign_in, token_of, world as world)
from ashley.signin.provider import Client
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from signin_support import CLIENT, oidc_for
from urllib.parse import parse_qs, urlsplit
import asyncio


def scopes_of(url: str) -> list[str]:
    return parse_qs(urlsplit(url).query)["scope"][0].split()


def authorize_scopes(group: str, idp: MultiIdp) -> list[str]:
    client = Client(CLIENT.issuer, CLIENT.client_id, CLIENT.client_secret, CLIENT.redirect_uri, admin_group=group)
    return scopes_of(asyncio.run(oidc_for(idp, client).authorize_url("s", "n", "c")))


def test_provider_mode_the_groups_scope_is_requested(idp: MultiIdp) -> None:
    got = authorize_scopes(GROUP, idp)
    assert "groups" in got and "openid" in got


def test_provider_mode_off_the_groups_scope_is_not_requested(idp: MultiIdp) -> None:
    assert "groups" not in authorize_scopes("", idp)


def test_provider_mode_a_member_of_the_group_is_admin_after_sign_in(provider_mode: TestClient, world: World,
                                                                     idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), [GROUP])
    assert me(provider_mode)["admin"] is True
    assert admin_flags(provider_mode)[world.sam] is True


def test_provider_mode_a_member_among_other_groups_is_admin(provider_mode: TestClient, world: World,
                                                            idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), ["a", GROUP, "b"])
    assert me(provider_mode)["admin"] is True


@pytest.mark.parametrize("groups", [None, [], ["other"], [GROUP + "x"], [GROUP.upper()]])
def test_provider_mode_a_person_outside_the_group_is_not_admin(provider_mode: TestClient, world: World, idp: MultiIdp,
                                                               groups: list[str] | None) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), groups)
    assert me(provider_mode)["admin"] is False


def test_provider_mode_a_former_admin_outside_the_group_loses_it_at_sign_in(provider_mode: TestClient, db_url: str,
                                                                            world: World, idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), [GROUP])
    assert me(provider_mode)["admin"] is True
    sign_in(provider_mode, idp, world.sub(world.sam), [])
    assert me(provider_mode)["admin"] is False


def test_provider_mode_a_former_admin_s_flag_in_the_app_does_not_make_them_admin(provider_mode: TestClient,
                                                                                  db_url: str, world: World,
                                                                                  idp: MultiIdp) -> None:
    set_admin(db_url, world.sam)
    sign_in(provider_mode, idp, world.sub(world.sam), [])
    assert me(provider_mode)["admin"] is False


def test_provider_mode_a_later_sign_in_outside_the_group_takes_power_from_a_session_already_live(
        provider_mode: TestClient, world: World, idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), [GROUP])
    live = token_of(provider_mode)
    assert me(provider_mode)["admin"] is True
    provider_mode.cookies.clear()
    sign_in(provider_mode, idp, world.sub(world.sam), [])
    as_(provider_mode, live)
    assert me(provider_mode)["admin"] is False


def test_provider_mode_a_session_already_live_loses_the_gated_power_too(provider_mode: TestClient, db_url: str,
                                                                        world: World, idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), [GROUP])
    live = token_of(provider_mode)
    assert admin_flags(provider_mode)[world.sam] is True
    provider_mode.cookies.clear()
    sign_in(provider_mode, idp, world.sub(world.sam), [])
    as_(provider_mode, live)
    assert codes(provider_mode.post("/api/connections", headers=ORIGIN,
                                    json={"kind": "anthropic", "label": "", "api_key": "sk-x"})) == (403, "admin_only")


def test_provider_mode_a_grant_reaches_a_live_session_opened_before_it(provider_mode: TestClient, world: World,
                                                                       idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), [])
    early = token_of(provider_mode)
    assert me(provider_mode)["admin"] is False
    provider_mode.cookies.clear()
    sign_in(provider_mode, idp, world.sub(world.sam), [GROUP])
    as_(provider_mode, early)
    assert me(provider_mode)["admin"] is True


def test_provider_mode_the_first_sign_in_on_an_empty_deployment_is_not_made_admin(provider_mode: TestClient,
                                                                                  world: World, idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.alana), [])
    assert me(provider_mode)["admin"] is False
    assert not any(admin_flags(provider_mode).values())


def test_provider_mode_no_sign_in_without_the_group_makes_an_earliest_person_admin(provider_mode: TestClient,
                                                                                  world: World, idp: MultiIdp) -> None:
    for person in (world.ivy, world.sam, world.kim):
        sign_in(provider_mode, idp, world.sub(person), None)
    sign_in(provider_mode, idp, world.sub(world.sam), [])
    assert not any(admin_flags(provider_mode).values())


def test_provider_mode_a_session_opened_before_the_group_was_set_is_no_admin_s(db_url: str, world: World,
                                                                               idp: MultiIdp,
                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    set_admin(db_url, world.alana)
    old = session_for(db_url, world, world.alana)
    with running(db_url, idp, monkeypatch, GROUP) as client:
        as_(client, old)
        assert me(client)["admin"] is False


def test_provider_mode_put_admin_is_409_admins_from_provider_and_changes_nothing(provider_mode: TestClient, db_url: str,
                                                                                 world: World, idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), [GROUP])
    before = admin_flags(provider_mode)
    for target, value in ((world.ivy, True), (world.sam, False), (world.sam, True)):
        assert codes(put_admin(provider_mode, target, value)) == (409, "admins_from_provider")
    assert admin_flags(provider_mode) == before
    assert me(provider_mode)["admin"] is True


def test_provider_mode_admins_from_is_provider(provider_mode: TestClient, world: World, idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.sam), [])
    assert people_listing(provider_mode)["admins_from"] == "provider"


def test_provider_mode_the_list_is_still_the_session_households_people(provider_mode: TestClient, world: World,
                                                                       idp: MultiIdp) -> None:
    sign_in(provider_mode, idp, world.sub(world.kim), [GROUP])
    assert [p["id"] for p in people_listing(provider_mode)["people"]] == [world.kim]


def test_provider_mode_unsetting_the_group_returns_to_each_person_s_flag_as_the_group_last_set_it(
        db_url: str, world: World, idp: MultiIdp, monkeypatch: pytest.MonkeyPatch) -> None:
    with running(db_url, idp, monkeypatch, GROUP) as client:
        sign_in(client, idp, world.sub(world.sam), [GROUP])
        sign_in(client, idp, world.sub(world.ivy), [])
        sam, ivy = session_for(db_url, world, world.sam), session_for(db_url, world, world.ivy)
    assert admin_ids(db_url) == [world.sam]
    with running(db_url, idp, monkeypatch) as client:
        as_(client, sam)
        assert me(client)["admin"] is True
        as_(client, ivy)
        assert me(client)["admin"] is False
        assert people_listing(client)["admins_from"] == "app"


def test_provider_mode_unsetting_the_group_with_no_admin_left_makes_the_earliest_person_admin_at_next_sign_in(
        db_url: str, world: World, idp: MultiIdp, monkeypatch: pytest.MonkeyPatch) -> None:
    with running(db_url, idp, monkeypatch, GROUP) as client:
        sign_in(client, idp, world.sub(world.sam), [GROUP])
        sign_in(client, idp, world.sub(world.sam), [])
    assert admin_ids(db_url) == []
    with running(db_url, idp, monkeypatch) as client:
        sign_in(client, idp, world.sub(world.ivy))
        assert admin_ids(db_url) == [world.alana]
        assert me(client)["admin"] is False


def test_provider_mode_a_sign_in_without_the_groups_claim_in_the_token_is_not_a_failure(
        provider_mode: TestClient, world: World, idp: MultiIdp) -> None:
    done: httpx2.Response = sign_in(provider_mode, idp, world.sub(world.sam), None)
    assert done.status_code == 302 and "failed" not in done.headers["location"]


def test_provider_mode_the_list_does_not_show_the_app_s_flag_as_admin(provider_mode: TestClient, db_url: str,
                                                                      world: World, idp: MultiIdp) -> None:
    set_admin(db_url, world.alana)
    sign_in(provider_mode, idp, world.sub(world.sam), [GROUP])
    assert admin_flags(provider_mode) == {world.alana: False, world.sam: True, world.ivy: False}
