"""Renewal: an access token is reused until it is within `refresh_margin_s` of expiry, and renewed by a compare-and-set on
`secret_version`, so two pods refreshing at once leave the winner's tokens and a rotated refresh token is never
overwritten by a stale one."""

import asyncio

from ashley.connections.oauth import OAuthUnavailable
from ashley.connections.renewal import NeedsReconnect
from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import DAY, FakeGoogle
from mail_oauth_blind_support import (People, access_token, as_, connected, fresh, in_app, needs, opened_secret, rows,
                                      the_google, version)

WITHIN = 1
OUTSIDE = 30 * DAY


def test_an_access_token_far_from_expiry_is_reused_without_asking_google(client: TestClient, fake: FakeGoogle,
                                                                         people: People) -> None:
    fake.expires_in = OUTSIDE
    cid, _, access = connected(client, fake, people)
    assert fresh(client, people, cid) == access and fresh(client, people, cid) == access
    assert fake.calls("token", "refresh_token") == 0


def test_an_access_token_within_the_margin_is_renewed_once_and_then_reused(client: TestClient, fake: FakeGoogle,
                                                                           people: People) -> None:
    fake.expires_in = WITHIN
    cid, _, first = connected(client, fake, people)
    fake.expires_in = OUTSIDE
    renewed = fresh(client, people, cid)
    assert renewed != first and renewed == fake.issued_access[-1]
    assert fake.calls("token", "refresh_token") == 1
    assert fresh(client, people, cid) == renewed and fake.calls("token", "refresh_token") == 1


def test_the_refresh_presents_the_stored_refresh_token_and_the_clients_credentials(
        client: TestClient, fake: FakeGoogle, people: People) -> None:
    fake.expires_in = WITHIN
    cid, refresh, _ = connected(client, fake, people)
    fresh(client, people, cid)
    (sent,) = [s for s in fake.seen if s.form.get("grant_type") == "refresh_token"]
    assert sent.form["refresh_token"] == refresh
    assert fake.calls("token") == 2


def test_the_expiry_is_the_one_the_provider_answered(client: TestClient, fake: FakeGoogle, people: People) -> None:
    fake.expires_in = WITHIN
    cid, _, _ = connected(client, fake, people)
    fake.expires_in = OUTSIDE
    fresh(client, people, cid)
    fake.expires_in = WITHIN
    for _ in range(3):
        assert fresh(client, people, cid) == fake.issued_access[1]
    assert fake.calls("token", "refresh_token") == 1


def test_a_renewal_that_sends_no_refresh_token_keeps_the_stored_one(client: TestClient, fake: FakeGoogle,
                                                                    people: People) -> None:
    fake.expires_in = WITHIN
    cid, refresh, _ = connected(client, fake, people)
    assert fake.rotate is False
    fresh(client, people, cid)
    assert opened_secret(client, people, cid) == refresh


def test_a_rotated_refresh_token_is_stored_and_used_next(client: TestClient, fake: FakeGoogle, people: People) -> None:
    fake.expires_in = WITHIN
    cid, refresh, _ = connected(client, fake, people)
    fake.rotate = fake.strict_rotation = True
    fresh(client, people, cid)
    rotated = fake.issued_refresh[-1]
    assert rotated != refresh and opened_secret(client, people, cid) == rotated
    fresh(client, people, cid)
    sent = [s.form["refresh_token"] for s in fake.seen if s.form.get("grant_type") == "refresh_token"]
    assert sent == [refresh, rotated]


def test_a_renewal_raises_the_secret_version(client: TestClient, fake: FakeGoogle, people: People, db_url: str) -> None:
    fake.expires_in = WITHIN
    cid, _, _ = connected(client, fake, people)
    before = version(db_url, cid)
    fresh(client, people, cid)
    assert version(db_url, cid) > before


def test_a_reuse_leaves_the_secret_version_alone(client: TestClient, fake: FakeGoogle, people: People,
                                                 db_url: str) -> None:
    fake.expires_in = OUTSIDE
    cid, _, _ = connected(client, fake, people)
    before = version(db_url, cid)
    fresh(client, people, cid)
    assert version(db_url, cid) == before


def _race(client: TestClient, fake: FakeGoogle, people: People, db_url: str, cid: int) -> dict[str, object]:
    """The first refresh is in flight when another pod's whole refresh lands: that one wins."""
    won: dict[str, object] = {}

    async def other_pod() -> None:
        won["access"] = await access_token(cid, people.home, people.alana)
        won["version"] = version(db_url, cid)

    fake.in_refresh = other_pod
    fake.expires_in = OUTSIDE

    async def pod() -> str | None:
        return await access_token(cid, people.home, people.alana)

    won["loser"] = in_app(client, pod)
    return won


def test_the_loser_of_two_refreshes_rereads_and_uses_the_winners_token(client: TestClient, fake: FakeGoogle,
                                                                       people: People, db_url: str) -> None:
    fake.expires_in = WITHIN
    cid, _, _ = connected(client, fake, people)
    won = _race(client, fake, people, db_url, cid)
    assert fake.calls("token", "refresh_token") == 2
    assert won["loser"] == won["access"]
    assert version(db_url, cid) == won["version"]


def test_a_stale_rotated_refresh_token_never_overwrites_the_winners(client: TestClient, fake: FakeGoogle,
                                                                    people: People, db_url: str) -> None:
    fake.expires_in = WITHIN
    cid, _, _ = connected(client, fake, people)
    fake.rotate = True
    won = _race(client, fake, people, db_url, cid)
    winner_refresh, loser_refresh = fake.issued_refresh[-2], fake.issued_refresh[-1]
    assert winner_refresh != loser_refresh
    assert opened_secret(client, people, cid) == winner_refresh
    assert won["loser"] == won["access"] and version(db_url, cid) == won["version"]


def test_the_winners_access_token_and_refresh_token_stay_a_pair(client: TestClient, fake: FakeGoogle,
                                                                people: People) -> None:
    fake.expires_in = WITHIN
    cid, _, _ = connected(client, fake, people)
    fake.rotate = True
    fake.expires_in = OUTSIDE

    async def many() -> list[str | None]:
        return list(await asyncio.gather(*(access_token(cid, people.home, people.alana) for _ in range(4))))

    got = in_app(client, many)
    first = got[0]
    assert len(set(got)) == 1 and first is not None
    assert fake.paired[first] == opened_secret(client, people, cid)
    assert fresh(client, people, cid) == first


def test_a_person_cannot_renew_another_persons_connection(client: TestClient, fake: FakeGoogle, people: People) -> None:
    fake.expires_in = WITHIN
    cid, _, _ = connected(client, fake, people)
    as_(client, people, "sam")
    calls = fake.calls("token")
    try:
        got = fresh(client, people, cid, "sam")
    except Exception:
        got = None
    assert got is None and fake.calls("token") == calls


def test_a_provider_that_fails_without_refusing_the_grant_marks_nothing(client: TestClient, fake: FakeGoogle,
                                                                        people: People, db_url: str) -> None:
    fake.expires_in = WITHIN
    cid, refresh, _ = connected(client, fake, people)
    for broken, status in ((True, None), (False, 503), (False, 429)):
        fake.refresh_down, fake.refresh_status = broken, status
        try:
            fresh(client, people, cid)
        except OAuthUnavailable:
            pass
        else:
            raise AssertionError(f"down={broken} status={status} did not raise OAuthUnavailable")
        assert needs(db_url, cid) is None and rows(db_url) == 1
        assert opened_secret(client, people, cid) == refresh


def test_a_refused_refresh_marks_the_connection_for_reconnect_and_keeps_the_row(
        client: TestClient, fake: FakeGoogle, people: People, db_url: str) -> None:
    fake.expires_in = WITHIN
    cid, refresh, _ = connected(client, fake, people)
    fake.refuse_refresh = True
    try:
        fresh(client, people, cid)
    except NeedsReconnect:
        pass
    else:
        raise AssertionError("a refused refresh did not raise NeedsReconnect")
    assert needs(db_url, cid) == "reconnect"
    assert rows(db_url) == 1 and opened_secret(client, people, cid) == refresh
    assert the_google(client)["needs"] == "reconnect" and the_google(client)["id"] == cid


def test_a_connection_that_needs_reconnect_answers_so_every_time(client: TestClient, fake: FakeGoogle,
                                                                 people: People) -> None:
    fake.expires_in = WITHIN
    cid, _, _ = connected(client, fake, people)
    fake.refuse_refresh = True
    for _ in range(3):
        try:
            fresh(client, people, cid)
        except NeedsReconnect:
            continue
        raise AssertionError("did not raise NeedsReconnect")
    fake.refuse_refresh = False
    try:
        fresh(client, people, cid)
    except NeedsReconnect:
        return
    raise AssertionError("a marked connection renewed on its own")
