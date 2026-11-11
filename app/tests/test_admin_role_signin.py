"""Who is an admin after a sign-in, through the real routes and database with a fake provider (`decisions.md`, "An admin
changes what the deployment shares"). With `ADMIN_GROUP` unset the app decides: whenever nobody is an admin, the earliest
person of the first household becomes one, whoever signed in. Set, the provider's `groups` claim alone decides, at each
sign-in, granting and revoking, on every live session of the person."""

import pytest
from admin_role_support import (GROUP, Deployment, admins, app_client, as_browser, deployment, me_admin, set_admin,
                                sign_in)
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from signin_support import FakeIdp



@pytest.fixture
def home(db_url: str) -> Deployment:
    return deployment(db_url)


@pytest.fixture
def fake() -> FakeIdp:
    return FakeIdp()


def test_with_no_admin_a_sign_in_makes_the_earliest_first_household_person_admin(home: Deployment,
                                                                                  fake: FakeIdp) -> None:
    for client in app_client(home.url, fake):
        sign_in(client, fake, "sub-ben")
        assert not me_admin(client)
        assert admins(home.url) == [home.ana]
        sign_in(client, fake, "sub-ana")
        assert me_admin(client)


def test_with_an_admin_a_sign_in_makes_no_other(home: Deployment, fake: FakeIdp) -> None:
    set_admin(home.url, home.cy)
    for client in app_client(home.url, fake):
        sign_in(client, fake, "sub-ana", groups=[GROUP])
        assert not me_admin(client)
        sign_in(client, fake, "sub-cy")
        assert me_admin(client)
    assert admins(home.url) == [home.cy]


def test_under_the_group_the_first_sign_in_is_no_admin_and_a_member_is_one(home: Deployment, fake: FakeIdp) -> None:
    for client in app_client(home.url, fake, GROUP):
        sign_in(client, fake, "sub-ana")
        assert not me_admin(client)
        sign_in(client, fake, "sub-cy", groups=["someone-else", GROUP])
        assert me_admin(client)
        listed = client.get("/api/people").json()
        assert listed["admins_from"] == "provider"
        assert {p["id"]: p["admin"] for p in listed["people"]} == {home.ana: False, home.ben: False, home.cy: True}


def test_under_the_group_a_former_admin_left_out_of_it_loses_it_on_every_session(home: Deployment,
                                                                                 fake: FakeIdp) -> None:
    for client in app_client(home.url, fake, GROUP):
        first = sign_in(client, fake, "sub-ben", groups=[GROUP])
        assert me_admin(client)
        sign_in(client, fake, "sub-ben", groups=[])
        assert not me_admin(client)
        as_browser(client, first)
        assert not me_admin(client)
    assert admins(home.url) == []


def test_under_the_group_an_admin_the_app_made_is_none_even_on_a_live_session(home: Deployment, fake: FakeIdp) -> None:
    token = ""
    for client in app_client(home.url, fake):
        token = sign_in(client, fake, "sub-ana")
        assert me_admin(client)
    for client in app_client(home.url, fake, GROUP):
        as_browser(client, token)
        assert not me_admin(client)
        assert client.get("/api/people").json()["admins_from"] == "provider"


def test_unsetting_the_group_with_no_admin_left_makes_the_earliest_person_admin_not_the_signer(
        home: Deployment, fake: FakeIdp) -> None:
    set_admin(home.url, home.ana)
    for client in app_client(home.url, fake, GROUP):
        sign_in(client, fake, "sub-ana", groups=[])
    assert admins(home.url) == []
    for client in app_client(home.url, fake):
        sign_in(client, fake, "sub-cy")
        assert not me_admin(client)
    assert admins(home.url) == [home.ana]


def test_unsetting_the_group_keeps_the_flags_it_last_set(home: Deployment, fake: FakeIdp) -> None:
    for client in app_client(home.url, fake, GROUP):
        sign_in(client, fake, "sub-ben", groups=[GROUP])
    for client in app_client(home.url, fake):
        sign_in(client, fake, "sub-cy")
        assert not me_admin(client)
        sign_in(client, fake, "sub-ben")
        assert me_admin(client)
    assert admins(home.url) == [home.ben]
