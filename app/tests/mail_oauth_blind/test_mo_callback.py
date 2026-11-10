"""The callback: the pending row is taken once and only for the person who started it, the code is redeemed with the
PKCE verifier, and a connection is stored only once the service answers with it."""

from collections.abc import Callable

import pytest
from ashley import services
from ashley.signin.model import LinkPending, Pending
from ashley.signin.sessions import Sessions
from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import FakeGoogle, s256
from mail_oauth_blind_support import (REDIRECT_URI, SCOPES, People, age_pending, as_, back, begin, in_app, listed,
                                      outcome, pending, pending_hashed, rows, start, the_google)


def test_a_connect_stores_the_connection_the_start_chose_and_shows_it_checked(
        client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    code, state = start(client, fake, "work")
    assert outcome(back(client, code=code, state=state)) == "connected"
    shown = the_google(client)
    assert shown["label"] == "work" and shown["kind"] == "google" and shown["personal"] is True
    assert shown["needs"] is None and shown["checked_at"] and rows(db_url) == 1
    assert pending(db_url) == 0


def test_the_callback_reads_nothing_but_the_code_and_state_from_its_query(client: TestClient, fake: FakeGoogle) -> None:
    code, state = start(client, fake, "work")
    extra = {"kind": "sure", "label": "evil", "holder": "household", "base_url": "https://evil.test", "person": "9"}
    assert outcome(back(client, code=code, state=state, **extra)) == "connected"
    shown = the_google(client)
    assert (shown["label"], shown["kind"], shown["personal"]) == ("work", "google", True)
    assert [c["kind"] for c in client.get("/api/connections").json()["connections"]] == ["google"]


def test_the_code_is_redeemed_with_the_verifier_the_challenge_committed_to(client: TestClient, fake: FakeGoogle) -> None:
    code, state = start(client, fake)
    challenge = fake.codes[code].challenge
    assert outcome(back(client, code=code, state=state)) == "connected"
    (redeem,) = [s for s in fake.seen if s.kind == "token"]
    assert redeem.form["grant_type"] == "authorization_code" and redeem.form["code"] == code
    assert redeem.form["redirect_uri"] == REDIRECT_URI
    assert s256(redeem.form["code_verifier"]) == challenge


def test_a_wrong_verifier_stores_nothing(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    code, state = start(client, fake)
    fake.codes[code].challenge = s256("some other verifier")
    assert outcome(back(client, code=code, state=state)) != "connected"
    assert rows(db_url) == 0 and fake.calls("userinfo") == 0


def test_a_state_works_once(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    code, state = start(client, fake)
    assert outcome(back(client, code=code, state=state)) == "connected"
    assert pending_hashed(db_url, state) == 0
    again = fake.mint_code(s256("whatever"), REDIRECT_URI, SCOPES)
    assert outcome(back(client, code=again, state=state)) == "failed"
    assert fake.calls("token") == 1 and fake.calls("userinfo") == 1 and rows(db_url) == 1


def test_an_unknown_or_missing_state_is_failed_and_redeems_nothing(client: TestClient, fake: FakeGoogle,
                                                                  db_url: str) -> None:
    start(client, fake)
    code = fake.mint_code(s256("v"), REDIRECT_URI, SCOPES)
    assert outcome(back(client, code=code, state="not-a-state")) == "failed"
    assert outcome(back(client, code=code)) == "failed"
    assert fake.calls("token") == 0 and rows(db_url) == 0 and pending(db_url) == 1


def test_an_expired_pending_row_is_failed(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    code, state = start(client, fake)
    age_pending(db_url)
    assert outcome(back(client, code=code, state=state)) == "failed"
    assert rows(db_url) == 0 and fake.calls("token") == 0


def test_another_persons_callback_is_refused_and_stores_nothing(client: TestClient, fake: FakeGoogle, people: People,
                                                               db_url: str) -> None:
    code, state = start(client, fake)
    as_(client, people, "sam")
    assert outcome(back(client, code=code, state=state)) == "wrong_person"
    assert rows(db_url) == 0
    as_(client, people, "sam")
    assert listed(client) == []


def test_a_callback_for_a_person_in_another_household_is_refused(client: TestClient, fake: FakeGoogle,
                                                                 people: People, db_url: str) -> None:
    code, state = start(client, fake)
    as_(client, people, "kim")
    assert outcome(back(client, code=code, state=state)) == "wrong_person"
    assert rows(db_url) == 0


def test_a_callback_with_no_session_stores_nothing(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    code, state = start(client, fake)
    client.cookies.clear()
    assert outcome(back(client, code=code, state=state)) != "connected"
    assert rows(db_url) == 0 and fake.calls("token") == 0


def test_declining_at_google_is_cancelled_and_stores_nothing(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    _, state = start(client, fake)
    assert outcome(back(client, error="access_denied", state=state)) == "cancelled"
    assert rows(db_url) == 0 and fake.calls("token") == 0
    assert pending_hashed(db_url, state) == 0


def test_a_callback_with_a_state_and_no_code_is_failed(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    _, state = start(client, fake)
    assert outcome(back(client, state=state)) == "failed"
    assert rows(db_url) == 0 and fake.calls("token") == 0


def test_a_refused_code_stores_nothing(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    code, state = start(client, fake)
    fake.refuse_code = True
    assert outcome(back(client, code=code, state=state)) == "failed"
    assert rows(db_url) == 0 and fake.calls("userinfo") == 0


def test_a_grant_with_no_refresh_token_stores_nothing(client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    fake.omit_refresh = True
    code, state = start(client, fake)
    assert outcome(back(client, code=code, state=state)) != "connected"
    assert rows(db_url) == 0


@pytest.mark.parametrize("userinfo", ["unauthorized", "down", "no_email"])
def test_nothing_is_stored_unless_userinfo_answers_for_the_new_token(client: TestClient, fake: FakeGoogle,
                                                                    db_url: str, userinfo: str) -> None:
    fake.userinfo = userinfo
    code, state = start(client, fake)
    assert outcome(back(client, code=code, state=state)) != "connected"
    assert rows(db_url) == 0 and listed(client) == []


def test_userinfo_is_read_with_the_access_token_just_issued(client: TestClient, fake: FakeGoogle) -> None:
    code, state = start(client, fake)
    back(client, code=code, state=state)
    (read,) = [s for s in fake.seen if s.kind == "userinfo"]
    assert read.bearer == fake.issued_access[0] and read.method == "GET"


def test_the_service_being_down_after_the_code_answers_unavailable_not_connected(
        client: TestClient, fake: FakeGoogle, db_url: str) -> None:
    fake.userinfo = "down"
    code, state = start(client, fake)
    assert outcome(back(client, code=code, state=state)) in ("unavailable", "failed")
    assert rows(db_url) == 0


def test_no_request_goes_to_a_host_that_is_not_googles(client: TestClient, fake: FakeGoogle) -> None:
    code, state = start(client, fake)
    back(client, code=code, state=state)
    assert fake.seen and not [s for s in fake.seen if s.kind == "stray"]


# --- a state from another flow cannot complete this one, and this one's cannot complete theirs ---------------------


def seed_signin(client: TestClient, state: str) -> None:
    async def put() -> None:
        assert await services.get(Sessions).begin(state, Pending("signin-verifier-0001", "nonce", "/"))

    in_app(client, put)


def seed_link(client: TestClient, people: People, state: str) -> None:
    async def put() -> None:
        assert await services.get(Sessions).begin_link(state, LinkPending(people.home, people.alana,
                                                                           "link-verifier-0001"))

    in_app(client, put)


SEEDS: dict[str, tuple[Callable[[TestClient, People, str], None], str]] = {
    "signin": (lambda c, p, s: seed_signin(c, s), "signin-verifier-0001"),
    "discord_link": (seed_link, "link-verifier-0001"),
}


@pytest.mark.parametrize("flow", sorted(SEEDS))
def test_a_state_from_a_sign_in_or_a_discord_link_cannot_complete_a_connect(
        client: TestClient, fake: FakeGoogle, people: People, db_url: str, flow: str) -> None:
    seed, verifier = SEEDS[flow]
    state = f"{flow}-state-0123456789abcdef0123456789abcdef"
    seed(client, people, state)
    code = fake.mint_code(s256(verifier), REDIRECT_URI, SCOPES)
    assert outcome(back(client, code=code, state=state)) == "failed"
    assert rows(db_url) == 0 and fake.calls("token") == 0
    assert listed(client) == []


def test_a_connect_state_cannot_complete_a_discord_link_or_a_sign_in(
        client: TestClient, fake: FakeGoogle, people: People, db_url: str) -> None:
    _, state = start(client, fake)
    linked = client.get("/api/accounts/discord/callback", params={"state": state, "code": "x"})
    assert linked.status_code == 302 and linked.headers["location"] == "/connections?link=failed"
    signed = client.get("/api/auth/callback", params={"state": state, "code": "x"})
    assert signed.status_code in (302, 303, 307, 400, 401, 503)
    assert pending_hashed(db_url, state) == 1
    assert rows(db_url) == 0 and fake.calls("token") == 0


def test_two_people_connecting_keep_separate_connections(client: TestClient, fake: FakeGoogle, people: People,
                                                        db_url: str) -> None:
    code, state = start(client, fake)
    as_(client, people, "sam")
    assert begin(client).status_code == 201
    as_(client, people, "alana")
    assert outcome(back(client, code=code, state=state)) == "connected"
    assert rows(db_url) == 1 and pending(db_url) == 1
    as_(client, people, "sam")
    assert listed(client) == []
