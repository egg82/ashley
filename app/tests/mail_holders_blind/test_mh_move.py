"""Handing a connection to the household and taking it back: who may, that the move reseals, and that a move past a
kind's `most` changes nothing."""

import pytest
from ashley import services
from ashley.connections.model import Grant
from ashley.connections.connections import ConnectionsUnavailable
from ashley.connections.oauth_connections import OAuthConnections
from fastapi.testclient import TestClient
from mail_holders_blind_support import (BOTH, HOME, ONE, ORIGIN, OWN, SECRET, People, as_, hand, holder_of, in_app, listing, make,
                                        one, opened_secret, opens_as, person_of, sealed, snapshot)


def test_handing_over_makes_it_the_households(client: TestClient, people: People, db_url: str) -> None:
    cid = make(client)
    got = hand(client, cid, "household")
    assert got.status_code == 200, got.text
    assert got.json()["id"] == cid and holder_of(got.json()) == "household"
    assert person_of(db_url, cid) is None


def test_a_handed_over_connection_is_listed_to_every_member_and_opens_for_them(client: TestClient,
                                                                             people: People) -> None:
    cid = make(client)
    as_(client, people, "sam")
    assert cid not in listing(client)
    as_(client, people, "alana")
    hand(client, cid, "household")
    as_(client, people, "sam")
    assert cid in listing(client)
    assert opened_secret(client, people, cid, "sam") == SECRET


def test_the_move_keeps_the_row_its_label_and_its_adder(client: TestClient, people: People, db_url: str) -> None:
    cid = make(client, BOTH, "work")
    before = listing(client)[cid]
    after = hand(client, cid, "household").json()
    for key in ("id", "label", "kind", "base_url", "added_by"):
        assert after[key] == before[key]
    assert one(db_url, "SELECT added_by FROM connections WHERE id = %s", (cid,)) == people.alana


def test_handing_over_reseals_the_secret_to_the_household(client: TestClient, people: People, db_url: str) -> None:
    cid = make(client)
    hand(client, cid, "household")
    assert opens_as(db_url, people, cid, "secret", BOTH, None) == SECRET
    assert opens_as(db_url, people, cid, "secret", BOTH, people.alana) is None


def test_taking_it_back_reseals_the_secret_to_the_person(client: TestClient, people: People, db_url: str) -> None:
    cid = make(client)
    hand(client, cid, "household")
    got = hand(client, cid, "person")
    assert got.status_code == 200 and holder_of(got.json()) == "person"
    assert person_of(db_url, cid) == people.alana
    assert opens_as(db_url, people, cid, "secret", BOTH, people.alana) == SECRET
    assert opens_as(db_url, people, cid, "secret", BOTH, None) is None
    as_(client, people, "sam")
    assert cid not in listing(client)


def test_the_access_token_of_an_oauth_connection_is_resealed_with_the_secret(client: TestClient, people: People,
                                                                           db_url: str) -> None:
    async def add() -> int:
        grant = Grant(access_token="access-token-0001", refresh_token="refresh-token-0001", expires_in_s=3600,
                      scopes=("openid", "email"))
        return (await services.get(OAuthConnections).add_oauth(people.home, BOTH, "g", "https://music.test", grant,
                                                               people.alana)).id

    cid = in_app(client, add)
    hand(client, cid, "household")
    assert opens_as(db_url, people, cid, "secret", BOTH, None) == "refresh-token-0001"
    assert opens_as(db_url, people, cid, "access_token", BOTH, None) == "access-token-0001"
    hand(client, cid, "person")
    assert opens_as(db_url, people, cid, "access_token", BOTH, people.alana) == "access-token-0001"


@pytest.mark.parametrize("to", ["household", "person"])
def test_a_sealed_value_moved_without_resealing_does_not_open(client: TestClient, people: People, db_url: str,
                                                              to: str) -> None:
    cid = make(client)
    if to == "person":
        hand(client, cid, "household")
        one(db_url, "UPDATE connections SET person_id = %s WHERE id = %s RETURNING 1", (people.alana, cid))
        who = "alana"
    else:
        one(db_url, "UPDATE connections SET person_id = NULL WHERE id = %s RETURNING 1", (cid,))
        who = "sam"
    with pytest.raises(ConnectionsUnavailable):
        opened_secret(client, people, cid, who)


def test_only_the_one_who_added_it_takes_it_back(client: TestClient, people: People, db_url: str) -> None:
    cid = make(client)
    hand(client, cid, "household")
    before = snapshot(db_url, cid)
    as_(client, people, "sam")
    got = hand(client, cid, "person")
    assert got.status_code == 403, got.text
    assert snapshot(db_url, cid) == before
    assert person_of(db_url, cid) is None
    as_(client, people, "alana")
    assert hand(client, cid, "person").status_code == 200


def test_any_member_removes_a_household_connection(client: TestClient, people: People) -> None:
    cid = make(client)
    hand(client, cid, "household")
    as_(client, people, "sam")
    assert client.delete(f"/api/connections/{cid}", headers=ORIGIN).status_code == 204


@pytest.mark.parametrize("who", ["sam", "kim"])
def test_nobody_else_can_hand_over_a_persons_connection(client: TestClient, people: People, db_url: str,
                                                        who: str) -> None:
    cid = make(client)
    before = snapshot(db_url, cid)
    as_(client, people, who)
    got = hand(client, cid, "household")
    assert got.status_code == 404 and got.json()["code"] == "not_found"
    assert snapshot(db_url, cid) == before


def test_a_member_of_another_household_cannot_take_one_back(client: TestClient, people: People, db_url: str) -> None:
    cid = make(client)
    hand(client, cid, "household")
    before = snapshot(db_url, cid)
    as_(client, people, "kim")
    assert hand(client, cid, "person").status_code == 404
    assert snapshot(db_url, cid) == before


def test_a_kind_that_is_only_the_households_cannot_be_taken_by_a_person(client: TestClient, db_url: str) -> None:
    cid = make(client, HOME)
    before = snapshot(db_url, cid)
    got = hand(client, cid, "person")
    assert got.status_code == 422 and got.json()["code"] == "unsupported"
    assert snapshot(db_url, cid) == before


def test_a_kind_that_is_only_a_persons_cannot_be_handed_to_the_household(client: TestClient, db_url: str) -> None:
    cid = make(client, OWN)
    before = snapshot(db_url, cid)
    got = hand(client, cid, "household")
    assert got.status_code == 422 and got.json()["code"] == "unsupported"
    assert snapshot(db_url, cid) == before


def test_a_move_past_the_households_most_is_409_too_many_and_changes_nothing(client: TestClient, people: People,
                                                                          db_url: str) -> None:
    first = make(client, ONE)
    assert hand(client, first, "household").status_code == 200
    as_(client, people, "sam")
    second = make(client, ONE, "b")
    before, before_sealed = snapshot(db_url, second), sealed(db_url, second)
    got = hand(client, second, "household")
    assert got.status_code == 409 and got.json()["code"] == "too_many"
    assert snapshot(db_url, second) == before and sealed(db_url, second) == before_sealed
    assert person_of(db_url, second) == people.sam
    assert opened_secret(client, people, second, "sam") == SECRET


def test_taking_back_past_the_persons_most_is_409_too_many_and_changes_nothing(client: TestClient, people: People,
                                                                            db_url: str) -> None:
    first = make(client, ONE, "a")
    hand(client, first, "household")
    make(client, ONE, "b")
    before, before_sealed = snapshot(db_url, first), sealed(db_url, first)
    got = hand(client, first, "person")
    assert got.status_code == 409 and got.json()["code"] == "too_many"
    assert snapshot(db_url, first) == before and sealed(db_url, first) == before_sealed
    assert person_of(db_url, first) is None


def test_the_households_most_counts_only_the_households_and_a_persons_only_theirs(client: TestClient,
                                                                               people: People) -> None:
    mine = make(client, ONE, "mine")
    as_(client, people, "sam")
    sams = make(client, ONE, "sams")
    assert hand(client, sams, "household").status_code == 200
    as_(client, people, "alana")
    assert hand(client, mine, "household").status_code == 409
    other = make(client, BOTH, "b1")
    assert hand(client, other, "household").status_code == 200


def test_a_move_within_most_is_allowed_until_it_is_reached(client: TestClient) -> None:
    a, b = make(client, BOTH, "a"), make(client, BOTH, "b")
    assert hand(client, a, "household").status_code == 200
    assert hand(client, b, "household").status_code == 200
    c = make(client, BOTH, "c")
    assert hand(client, c, "household").status_code == 409


def test_a_move_across_origins_or_signed_out_is_refused_and_changes_nothing(client: TestClient, people: People,
                                                                         db_url: str) -> None:
    cid = make(client)
    before = snapshot(db_url, cid)
    assert hand(client, cid, "household", headers={"origin": "https://evil.test"}).status_code == 403
    client.cookies.clear()
    assert hand(client, cid, "household").status_code == 401
    assert snapshot(db_url, cid) == before


@pytest.mark.parametrize("holder", ["everyone", "", "Household"])
def test_any_other_holder_is_refused(client: TestClient, db_url: str, holder: str) -> None:
    cid = make(client)
    before = snapshot(db_url, cid)
    assert hand(client, cid, holder).status_code == 422
    assert snapshot(db_url, cid) == before


def test_a_connection_that_is_not_there_is_404(client: TestClient) -> None:
    assert hand(client, 987654, "household").status_code == 404


def test_renaming_still_works_beside_the_holder(client: TestClient) -> None:
    cid = make(client)
    got = client.patch(f"/api/connections/{cid}", json={"label": "work"}, headers=ORIGIN)
    assert got.status_code == 200 and got.json()["label"] == "work" and holder_of(got.json()) == "person"


def test_replacing_a_handed_over_connection_seals_it_to_the_household(client: TestClient, people: People,
                                                                   db_url: str) -> None:
    cid = make(client)
    hand(client, cid, "household")
    as_(client, people, "sam")
    got = client.put(f"/api/connections/{cid}", json={"base_url": "https://music.test", "token": "sams-new-0002"},
                     headers=ORIGIN)
    assert got.status_code == 200
    assert opens_as(db_url, people, cid, "secret", BOTH, None) == "sams-new-0002"
