"""Who holds a connection is declared by its kind as `holders`, and a connection's `person_id` says which holder it has."""

import dataclasses

from ashley.connections.kinds import ConnectionKind
from ashley.wiring import CONNECTION_KINDS
from fastapi.testclient import TestClient
from mail_holders_blind_support import BOTH, HOME, ONE, OWN, People, as_, holder_of, listing, make, person_of

REAL = {k.name: k for k in CONNECTION_KINDS}


def test_the_real_kinds_declare_who_may_hold_them() -> None:
    assert REAL["sure"].holders == {"household"}
    assert REAL["home_assistant"].holders == {"household"}
    assert REAL["gitlab"].holders == {"person"}
    assert REAL["github"].holders == {"person"}
    assert REAL["herdr"].holders == {"person"}
    assert REAL["google"].holders == {"household", "person"}


def test_a_kind_no_longer_has_a_personal_flag() -> None:
    assert "personal" not in {f.name for f in dataclasses.fields(ConnectionKind)}
    assert "holders" in {f.name for f in dataclasses.fields(ConnectionKind)}


def test_the_room_offers_each_kind_with_its_holders(client: TestClient) -> None:
    offered = {k["name"]: k for k in client.get("/api/connections").json()["offered"]}
    assert set(offered[BOTH]["holders"]) == {"household", "person"}
    assert set(offered[HOME]["holders"]) == {"household"}
    assert set(offered[OWN]["holders"]) == {"person"}


def test_a_household_only_kind_is_held_by_the_household(client: TestClient, db_url: str) -> None:
    cid = make(client, HOME)
    assert person_of(db_url, cid) is None
    assert holder_of(listing(client)[cid]) == "household"


def test_a_person_only_kind_is_held_by_the_person(client: TestClient, people: People, db_url: str) -> None:
    cid = make(client, OWN)
    assert person_of(db_url, cid) == people.alana
    assert holder_of(listing(client)[cid]) == "person"


def test_a_kind_either_may_hold_is_the_persons_until_handed_over(client: TestClient, people: People,
                                                                 db_url: str) -> None:
    cid = make(client, BOTH)
    assert person_of(db_url, cid) == people.alana
    assert holder_of(listing(client)[cid]) == "person"


def test_a_household_connection_is_listed_to_every_member_and_a_persons_to_its_owner(client: TestClient,
                                                                                     people: People) -> None:
    home, own = make(client, HOME), make(client, ONE)
    as_(client, people, "sam")
    assert set(listing(client)) == {home}
    as_(client, people, "alana")
    assert set(listing(client)) == {home, own}
