"""Starting an OAuth connect: a same-origin POST by a signed-in person stores a pending row bound to them, keyed by the
hash of its state, and answers Google's authorization URL carrying a PKCE challenge."""

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import CLIENT_ID, FakeGoogle, holds_verifier, s256
from mail_oauth_blind_support import (CALLBACK, PUBLIC, REDIRECT_URI, SCOPES, People, as_, back, begin,
                                      listed, outcome, pending, pending_hashed, pending_owner, row_text, rows, start)


def query_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_the_authorization_url_names_the_client_the_scopes_and_a_pkce_challenge(client: TestClient) -> None:
    started = begin(client)
    assert started.status_code == 201
    url: str = started.json()["authorize_url"]
    query = query_of(url)
    assert urlsplit(url).netloc == "accounts.google.com"
    assert query["client_id"] == CLIENT_ID and query["response_type"] == "code"
    assert query["redirect_uri"] == REDIRECT_URI and query["redirect_uri"] == PUBLIC + CALLBACK
    assert tuple(query["scope"].split()) == SCOPES
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) >= 43
    assert query["access_type"] == "offline"
    assert len(query["state"]) >= 32


def test_every_start_has_its_own_state_and_challenge(client: TestClient) -> None:
    first, second = (query_of(begin(client).json()["authorize_url"]) for _ in range(2))
    assert first["state"] != second["state"] and first["code_challenge"] != second["code_challenge"]


def test_a_start_stores_one_pending_row_for_the_person_keyed_by_the_hash_of_its_state(
        client: TestClient, db_url: str, people: People) -> None:
    state = query_of(begin(client).json()["authorize_url"])["state"]
    assert pending(db_url) == 1
    assert pending_hashed(db_url, state) == 1
    assert pending_owner(db_url) == people.alana
    assert state not in row_text(db_url)


def test_the_verifier_is_not_stored_in_the_clear_and_is_the_one_the_challenge_commits_to(
        client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    code, state = start(client, fake)
    challenge = fake.codes[code].challenge
    assert pending(db_url) == 1 and not holds_verifier(row_text(db_url), challenge)
    assert outcome(back(client, code=code, state=state)) == "connected"
    (verifier,) = fake.verifiers
    assert s256(verifier) == challenge


def test_a_start_from_another_site_is_forbidden_and_stores_nothing(client: TestClient, db_url: str) -> None:
    for headers in ({"sec-fetch-site": "cross-site"}, {"origin": "https://evil.test"}):
        refused = begin(client, headers=headers)
        assert refused.status_code == 403
    assert pending(db_url) == 0


def test_a_start_without_a_session_is_401(client: TestClient, db_url: str) -> None:
    client.cookies.clear()
    assert begin(client).status_code == 401
    assert pending(db_url) == 0


def test_unset_client_credentials_answer_503_and_store_nothing(unconfigured: TestClient, db_url: str,
                                                              fake: FakeGoogle) -> None:
    refused = begin(unconfigured)
    assert refused.status_code == 503
    assert pending(db_url) == 0 and rows(db_url) == 0
    assert fake.seen == []


def test_a_start_connects_nothing_by_itself(client: TestClient, db_url: str, fake: FakeGoogle) -> None:
    assert begin(client).status_code == 201
    assert rows(db_url) == 0 and listed(client) == [] and fake.seen == []


def test_a_started_connect_by_one_person_is_not_listed_for_another(client: TestClient, people: People) -> None:
    begin(client)
    as_(client, people, "sam")
    assert listed(client) == []
