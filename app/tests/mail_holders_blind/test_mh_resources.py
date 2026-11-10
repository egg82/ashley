"""A connection's resources: listed as the service names them when it is stored and each time the room is opened, each
shared or kept by its owner, and every resource of a household connection shared."""

from fastapi.testclient import TestClient
from mail_holders_blind_support import (BOTH, HOME, ORIGIN, SECRET, Boxes, People, as_, hand, listing, make,
                                        resources_of, share, snapshot, stored)


def test_a_stored_connection_lists_its_resources_as_the_service_names_them(client: TestClient, boxes: Boxes,
                                                                          db_url: str) -> None:
    boxes.refs = ["alana@home.test", "alana@work.test"]
    boxes.names = {"alana@home.test": "Home", "alana@work.test": "Work, with a comma"}
    cid = make(client)
    got = resources_of(client, cid)
    assert set(got) == {"alana@home.test", "alana@work.test"}
    assert got["alana@work.test"]["name"] == "Work, with a comma" and got["alana@work.test"]["kind"] == "mailbox"
    assert stored(db_url, cid) == [("alana@home.test", "mailbox", "Home", False),
                                   ("alana@work.test", "mailbox", "Work, with a comma", False)]


def test_the_service_is_opened_with_the_connections_own_secret(client: TestClient, boxes: Boxes) -> None:
    make(client)
    assert boxes.secrets and set(boxes.secrets) == {SECRET}


def test_each_resource_of_a_personal_connection_starts_kept(client: TestClient, boxes: Boxes) -> None:
    boxes.refs = ["a@x.test", "b@x.test"]
    cid = make(client)
    assert {r["shared"] for r in resources_of(client, cid).values()} == {False}


def test_every_resource_of_a_household_connection_is_shared(client: TestClient, boxes: Boxes, db_url: str) -> None:
    boxes.refs = ["a@x.test", "b@x.test"]
    cid = make(client, HOME)
    assert {r["shared"] for r in resources_of(client, cid).values()} == {True}
    assert {row[3] for row in stored(db_url, cid)} == {True}


def test_opening_the_room_lists_again_and_drops_what_disappeared(client: TestClient, boxes: Boxes,
                                                                 db_url: str) -> None:
    boxes.refs = ["a@x.test", "b@x.test"]
    cid = make(client)
    boxes.refs = ["b@x.test", "c@x.test"]
    calls = boxes.calls
    assert set(resources_of(client, cid)) == {"b@x.test", "c@x.test"}
    assert boxes.calls > calls
    assert [r[0] for r in stored(db_url, cid)] == ["b@x.test", "c@x.test"]


def test_a_shared_resource_stays_shared_across_a_reread_and_a_new_one_is_kept(client: TestClient,
                                                                              boxes: Boxes) -> None:
    boxes.refs = ["a@x.test"]
    cid = make(client)
    share(client, cid, "a@x.test")
    boxes.refs = ["a@x.test", "new@x.test"]
    got = resources_of(client, cid)
    assert got["a@x.test"]["shared"] is True and got["new@x.test"]["shared"] is False


def test_a_resource_the_service_renames_shows_its_new_name(client: TestClient, boxes: Boxes, db_url: str) -> None:
    cid = make(client)
    boxes.names = {"alana@home.test": "Renamed"}
    assert resources_of(client, cid)["alana@home.test"]["name"] == "Renamed"
    assert stored(db_url, cid)[0][2] == "Renamed"


def test_a_household_connections_new_resource_arrives_shared(client: TestClient, boxes: Boxes) -> None:
    cid = make(client, HOME)
    boxes.refs = ["alana@home.test", "new@x.test"]
    assert resources_of(client, cid)["new@x.test"]["shared"] is True


def test_the_owner_shares_a_resource_and_keeps_it_again(client: TestClient, boxes: Boxes, db_url: str) -> None:
    boxes.refs = ["a@x.test", "b@x.test"]
    cid = make(client)
    got = share(client, cid, "a@x.test")
    assert got.status_code == 200, got.text
    assert got.json()["ref"] == "a@x.test" and got.json()["shared"] is True
    assert resources_of(client, cid)["a@x.test"]["shared"] is True
    assert resources_of(client, cid)["b@x.test"]["shared"] is False
    assert dict((r[0], r[3]) for r in stored(db_url, cid)) == {"a@x.test": True, "b@x.test": False}
    assert share(client, cid, "a@x.test", False).json()["shared"] is False
    assert resources_of(client, cid)["a@x.test"]["shared"] is False


def test_sharing_a_ref_on_one_connection_does_not_share_it_on_another(client: TestClient, boxes: Boxes) -> None:
    boxes.refs = ["same@x.test"]
    one_id, two_id = make(client, BOTH, "one"), make(client, BOTH, "two")
    share(client, one_id, "same@x.test")
    assert resources_of(client, one_id)["same@x.test"]["shared"] is True
    assert resources_of(client, two_id)["same@x.test"]["shared"] is False


def test_nobody_but_the_owner_shares_a_persons_resource(client: TestClient, boxes: Boxes, people: People,
                                                        db_url: str) -> None:
    cid = make(client)
    before = snapshot(db_url, cid)
    for who in ("sam", "kim"):
        as_(client, people, who)
        got = share(client, cid, "alana@home.test")
        assert got.status_code == 404 and got.json()["code"] == "not_found"
    assert snapshot(db_url, cid) == before


def test_a_ref_the_connection_does_not_list_is_404(client: TestClient, db_url: str) -> None:
    cid = make(client)
    before = snapshot(db_url, cid)
    assert share(client, cid, "nobody@x.test").status_code == 404
    assert snapshot(db_url, cid) == before


def test_another_connections_ref_is_not_reachable_through_this_one(client: TestClient, boxes: Boxes,
                                                                   db_url: str) -> None:
    boxes.refs = ["only-on-one@x.test"]
    one_id = make(client, BOTH, "one")
    boxes.refs = ["only-on-two@x.test"]
    two_id = make(client, BOTH, "two")
    before = snapshot(db_url, two_id)
    assert share(client, one_id, "only-on-two@x.test").status_code == 404
    assert snapshot(db_url, two_id) == before


def test_a_member_cannot_keep_a_resource_of_a_household_connection(client: TestClient, db_url: str) -> None:
    cid = make(client, HOME)
    got = share(client, cid, "alana@home.test", False)
    assert 400 <= got.status_code < 500, got.text
    assert resources_of(client, cid)["alana@home.test"]["shared"] is True
    assert stored(db_url, cid)[0][3] is True


def test_handing_a_connection_over_shares_all_its_resources(client: TestClient, boxes: Boxes, people: People) -> None:
    boxes.refs = ["a@x.test", "b@x.test"]
    cid = make(client)
    share(client, cid, "a@x.test")
    hand(client, cid, "household")
    assert {r["shared"] for r in resources_of(client, cid).values()} == {True}
    as_(client, people, "sam")
    assert {r["shared"] for r in resources_of(client, cid).values()} == {True}


def test_a_persons_resources_are_not_listed_to_anyone_else(client: TestClient, people: People) -> None:
    cid = make(client)
    as_(client, people, "sam")
    assert cid not in listing(client)


def test_removing_a_connection_removes_its_resources(client: TestClient, boxes: Boxes, db_url: str) -> None:
    boxes.refs = ["a@x.test", "b@x.test"]
    cid = make(client)
    assert len(stored(db_url, cid)) == 2
    assert client.delete(f"/api/connections/{cid}", headers=ORIGIN).status_code == 204
    assert stored(db_url, cid) == []


def test_sharing_across_origins_or_signed_out_is_refused(client: TestClient, db_url: str) -> None:
    cid = make(client)
    before = snapshot(db_url, cid)
    assert share(client, cid, "alana@home.test", headers={"origin": "https://evil.test"}).status_code == 403
    client.cookies.clear()
    assert share(client, cid, "alana@home.test").status_code == 401
    assert snapshot(db_url, cid) == before


def test_a_body_that_is_not_a_boolean_is_refused(client: TestClient, db_url: str) -> None:
    cid = make(client)
    before = snapshot(db_url, cid)
    got = client.patch(f"/api/connections/{cid}/resources/alana@home.test", json={"shared": "maybe"}, headers=ORIGIN)
    assert got.status_code == 422
    assert snapshot(db_url, cid) == before

