"""App mode (`ADMIN_GROUP` unset): the people routes, who may grant and revoke admin, the last admin, and another
household's people."""

from admin_role_blind_support import (ORIGIN, World, admin_flags, admin_ids, app_mode as app_mode, as_, codes, idp as idp,
                                      people_listing, put_admin, session_for, set_admin, world as world)
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient


def sign_in_as(client: TestClient, db_url: str, world: World, person: int) -> None:
    as_(client, session_for(db_url, world, person))


def test_app_mode_the_list_is_the_session_households_people_only(app_mode: TestClient, db_url: str, world: World) -> None:
    sign_in_as(app_mode, db_url, world, world.sam)
    assert [p["id"] for p in people_listing(app_mode)["people"]] == [world.alana, world.sam, world.ivy]
    sign_in_as(app_mode, db_url, world, world.kim)
    assert [p["id"] for p in people_listing(app_mode)["people"]] == [world.kim]


def test_app_mode_the_list_carries_admin_per_person(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    set_admin(db_url, world.ivy)
    sign_in_as(app_mode, db_url, world, world.sam)
    assert admin_flags(app_mode) == {world.alana: True, world.sam: False, world.ivy: True}


def test_app_mode_the_list_says_admins_from_app(app_mode: TestClient, db_url: str, world: World) -> None:
    sign_in_as(app_mode, db_url, world, world.sam)
    assert people_listing(app_mode)["admins_from"] == "app"


def test_app_mode_the_list_names_each_person_with_id_household_name_and_admin(app_mode: TestClient, db_url: str,
                                                                               world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.alana)
    first = people_listing(app_mode)["people"][0]
    assert first == {"id": world.alana, "household_id": world.home, "name": "Alana", "admin": True}


def test_app_mode_the_list_needs_a_session(app_mode: TestClient) -> None:
    app_mode.cookies.clear()
    assert app_mode.get("/api/people").status_code == 401


def test_app_mode_an_admin_grants_and_the_answer_is_the_person(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.alana)
    got = put_admin(app_mode, world.sam, True)
    assert got.status_code == 200, got.text
    assert got.json() == {"id": world.sam, "household_id": world.home, "name": "Sam", "admin": True}
    assert admin_ids(db_url) == [world.alana, world.sam]
    assert admin_flags(app_mode)[world.sam] is True


def test_app_mode_an_admin_revokes_another_admin(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    set_admin(db_url, world.sam)
    sign_in_as(app_mode, db_url, world, world.alana)
    got = put_admin(app_mode, world.sam, False)
    assert got.status_code == 200 and got.json()["admin"] is False
    assert admin_ids(db_url) == [world.alana]


def test_app_mode_a_grant_to_one_already_admin_is_still_200(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.alana)
    got = put_admin(app_mode, world.alana, True)
    assert got.status_code == 200 and got.json()["admin"] is True


def test_app_mode_a_grant_takes_effect_on_the_grantee_s_live_session(app_mode: TestClient, db_url: str,
                                                                      world: World) -> None:
    set_admin(db_url, world.alana)
    sam = session_for(db_url, world, world.sam)
    sign_in_as(app_mode, db_url, world, world.alana)
    assert put_admin(app_mode, world.sam, True).status_code == 200
    as_(app_mode, sam)
    assert app_mode.get("/api/me").json()["person"]["admin"] is True


def test_app_mode_a_non_admin_s_put_is_403_admin_only_and_changes_nothing(app_mode: TestClient, db_url: str,
                                                                          world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.sam)
    for target, value in ((world.sam, True), (world.ivy, True), (world.alana, False)):
        assert codes(put_admin(app_mode, target, value)) == (403, "admin_only")
    assert admin_ids(db_url) == [world.alana]


def test_app_mode_a_person_in_another_household_is_404_and_unchanged(app_mode: TestClient, db_url: str,
                                                                     world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.alana)
    assert codes(put_admin(app_mode, world.kim, True)) == (404, "not_found")
    assert admin_ids(db_url) == [world.alana]


def test_app_mode_an_admin_of_another_household_reaches_no_one_here(app_mode: TestClient, db_url: str,
                                                                    world: World) -> None:
    set_admin(db_url, world.alana)
    set_admin(db_url, world.kim)
    sign_in_as(app_mode, db_url, world, world.kim)
    assert codes(put_admin(app_mode, world.sam, True)) == (404, "not_found")
    assert codes(put_admin(app_mode, world.alana, False)) == (404, "not_found")
    assert admin_ids(db_url) == [world.alana, world.kim]


def test_app_mode_an_id_nobody_has_is_404(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.alana)
    assert codes(put_admin(app_mode, 999999, True)) == (404, "not_found")


def test_app_mode_revoking_the_last_admin_is_409_last_admin_and_changes_nothing(app_mode: TestClient, db_url: str,
                                                                                 world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.alana)
    assert codes(put_admin(app_mode, world.alana, False)) == (409, "last_admin")
    assert admin_ids(db_url) == [world.alana]


def test_app_mode_the_last_admin_is_counted_across_households(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    set_admin(db_url, world.kim)
    sign_in_as(app_mode, db_url, world, world.alana)
    got = put_admin(app_mode, world.alana, False)
    assert got.status_code == 200, "another household's admin is still an admin of the deployment"
    assert admin_ids(db_url) == [world.kim]


def test_app_mode_one_of_two_admins_may_revoke_themselves_once(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    set_admin(db_url, world.sam)
    sign_in_as(app_mode, db_url, world, world.alana)
    assert put_admin(app_mode, world.alana, False).status_code == 200
    assert admin_ids(db_url) == [world.sam]
    sign_in_as(app_mode, db_url, world, world.sam)
    assert codes(put_admin(app_mode, world.sam, False)) == (409, "last_admin")


def test_app_mode_a_body_with_more_than_admin_is_422(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.alana)
    sign_in_as(app_mode, db_url, world, world.alana)
    got = app_mode.put(f"/api/people/{world.sam}/admin", json={"admin": True, "name": "x"}, headers=ORIGIN)
    assert got.status_code == 422
    assert admin_ids(db_url) == [world.alana]
