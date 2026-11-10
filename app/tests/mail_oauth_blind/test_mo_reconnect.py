"""Connecting again over a connection replaces its secret and clears `needs`, for that owner's connection only."""

from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import DAY, FakeGoogle
from mail_oauth_blind_support import (People, as_, connect, connected, fresh, listed, needs, opened_secret, rows,
                                      the_google, version)


def refused(client: TestClient, fake: FakeGoogle, people: People) -> int:
    fake.expires_in = 1
    cid, _, _ = connected(client, fake, people)
    fake.refuse_refresh = True
    try:
        fresh(client, people, cid)
    except Exception:
        pass
    fake.refuse_refresh = False
    fake.expires_in = DAY
    return cid


def test_reconnecting_replaces_the_secret_keeps_the_row_and_clears_needs(
        client: TestClient, fake: FakeGoogle, people: People, db_url: str) -> None:
    cid = refused(client, fake, people)
    assert needs(db_url, cid) == "reconnect"
    old, before = opened_secret(client, people, cid), version(db_url, cid)
    assert connect(client, fake) == "connected"
    assert rows(db_url) == 1 and the_google(client)["id"] == cid
    assert needs(db_url, cid) is None and the_google(client)["needs"] is None
    assert opened_secret(client, people, cid) != old
    assert opened_secret(client, people, cid) == fake.issued_refresh[-1]
    assert version(db_url, cid) > before


def test_the_reconnected_connection_gives_the_new_access_token_without_asking_again(
        client: TestClient, fake: FakeGoogle, people: People) -> None:
    cid = refused(client, fake, people)
    connect(client, fake)
    calls = fake.calls("token", "refresh_token")
    assert fresh(client, people, cid) == fake.issued_access[-1]
    assert fake.calls("token", "refresh_token") == calls


def test_a_refused_reconnect_leaves_the_mark_and_the_old_secret(client: TestClient, fake: FakeGoogle, people: People,
                                                                db_url: str) -> None:
    cid = refused(client, fake, people)
    old = opened_secret(client, people, cid)
    fake.userinfo = "unauthorized"
    assert connect(client, fake) != "connected"
    assert needs(db_url, cid) == "reconnect" and opened_secret(client, people, cid) == old
    assert rows(db_url) == 1


def test_reconnecting_never_touches_another_persons_connection(client: TestClient, fake: FakeGoogle,
                                                               people: People, db_url: str) -> None:
    sam_id, sam_refresh, _ = connected(client, fake, people, "sam")
    as_(client, people, "alana")
    assert connect(client, fake) == "connected"
    assert rows(db_url) == 2
    assert opened_secret(client, people, sam_id, "sam") == sam_refresh
    assert [c["id"] for c in listed(client)] != [sam_id]


def test_a_second_connect_by_the_same_owner_is_not_a_second_row(client: TestClient, fake: FakeGoogle,
                                                                people: People, db_url: str) -> None:
    assert connect(client, fake) == "connected"
    first = the_google(client)["id"]
    assert connect(client, fake) == "connected"
    assert rows(db_url) == 1 and the_google(client)["id"] == first
