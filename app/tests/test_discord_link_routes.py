"""Linking a Discord account end to end through the real app, a real database and the fake Discord: a signed-in person
links, sees and unlinks their Discord account; a link is refused when that account is another person's, when the
person signed in is not the one who started it, when its state is reused, unknown or missing a session, or when they
declined at Discord; unconfigured, starting is 503 and the list says so; nothing secret or personal is logged."""

import hashlib
import secrets
from collections.abc import Generator
from dataclasses import dataclass

import psycopg
import pytest
from ashley import services
from ashley.api.models import AccountsResponse, ErrorResponse, LinkedAccount, LinkStartResponse
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.signin.discord import DiscordOAuth, DiscordUser
from ashley.signin.identity import sub_prefix
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from discord_link_support import FakeDiscord
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
CALLBACK = "/api/accounts/discord/callback"


@dataclass(frozen=True)
class Home:
    household: int
    alana: int
    sam: int
    alana_token: str
    sam_token: str
    alana_signin_account: int


def _session(conn: psycopg.Connection, account_id: int, household_id: int) -> str:
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account_id, household_id))
    return token


@pytest.fixture
def home(db_url: str) -> Home:
    with psycopg.connect(db_url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        alana, sam = admin.add_person(conn, hid, "Alana"), admin.add_person(conn, hid, "Sam")
        alana_signin = admin.add_account(conn, alana, "oidc", "sub-alana")
        sam_signin = admin.add_account(conn, sam, "oidc", "sub-sam")
        return Home(hid, alana, sam, _session(conn, alana_signin, hid), _session(conn, sam_signin, hid), alana_signin)


@pytest.fixture
def fake() -> FakeDiscord:
    return FakeDiscord()


@pytest.fixture
def client(db_url: str, home: Home, fake: FakeDiscord) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    services.register(DiscordOAuth, fake)
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, home.alana_token, domain="ashley.test")
        yield c
    services.unregister(DiscordOAuth)


def as_(client: TestClient, token: str) -> None:
    client.cookies.set(SESSION_COOKIE, token, domain="ashley.test")


def start(client: TestClient, fake: FakeDiscord) -> tuple[str, str]:
    started = client.post("/api/accounts/discord/link", headers=ORIGIN)
    assert started.status_code == 201
    return fake.authorize(LinkStartResponse.model_validate(started.json()).authorize_url)


def back(client: TestClient, **query: str) -> str:
    done = client.get(CALLBACK, params=query)
    assert done.status_code == 302
    return done.headers["location"]


def accounts(client: TestClient) -> AccountsResponse:
    listed = client.get("/api/accounts")
    assert listed.status_code == 200
    return AccountsResponse.model_validate(listed.json())


def discord_owner(db_url: str, external_id: str) -> int:
    return int(scalar(db_url, "SELECT coalesce(max(person_id), 0) FROM accounts "
                              "WHERE system = 'discord' AND external_id = %s", (external_id,)))


def test_a_person_links_sees_and_unlinks_their_discord(client: TestClient, fake: FakeDiscord, home: Home,
                                                      db_url: str) -> None:
    before = accounts(client)
    assert before.discord_linking
    assert before.accounts == [LinkedAccount(id=home.alana_signin_account, system="oidc", handle=None,
                                             unlinkable=False)]
    code, state = start(client, fake)
    assert back(client, code=code, state=state) == "/connections?link=linked"
    assert discord_owner(db_url, fake.user.id) == home.alana
    linked = accounts(client).accounts[1]
    assert (linked.system, linked.handle, linked.unlinkable) == ("discord", "zqHANDLE", True)
    gone = client.delete(f"/api/accounts/{linked.id}", headers=ORIGIN)
    assert gone.status_code == 204
    assert discord_owner(db_url, fake.user.id) == 0
    again = client.delete(f"/api/accounts/{linked.id}", headers=ORIGIN)
    assert again.status_code == 404 and ErrorResponse.model_validate(again.json()).code == "not_found"


def test_linking_the_same_account_again_keeps_it_and_takes_the_new_handle(client: TestClient, fake: FakeDiscord,
                                                                         home: Home) -> None:
    code, state = start(client, fake)
    back(client, code=code, state=state)
    first = accounts(client).accounts[1]
    fake.user = DiscordUser(fake.user.id, "zqRENAMED")
    code, state = start(client, fake)
    assert back(client, code=code, state=state) == "/connections?link=linked"
    assert accounts(client).accounts[1:] == [first.model_copy(update={"handle": "zqRENAMED"})]


def test_an_account_another_person_has_is_refused_and_left_theirs(client: TestClient, fake: FakeDiscord, home: Home,
                                                                  db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        admin.add_account(conn, home.sam, "discord", fake.user.id)
    code, state = start(client, fake)
    assert back(client, code=code, state=state) == "/connections?link=taken"
    assert discord_owner(db_url, fake.user.id) == home.sam
    assert [a.system for a in accounts(client).accounts] == ["oidc"]


def test_a_link_finishes_only_for_the_person_who_started_it(client: TestClient, fake: FakeDiscord, home: Home,
                                                            db_url: str) -> None:
    code, state = start(client, fake)
    as_(client, home.sam_token)
    assert back(client, code=code, state=state) == "/connections?link=wrong_person"
    assert discord_owner(db_url, fake.user.id) == 0
    as_(client, home.alana_token)
    assert back(client, code=code, state=state) == "/connections?link=failed", "the state was taken by the refusal"
    assert discord_owner(db_url, fake.user.id) == 0


def test_a_state_is_taken_once(client: TestClient, fake: FakeDiscord, home: Home, db_url: str) -> None:
    code, state = start(client, fake)
    grant = fake.grants[code]
    assert back(client, code=code, state=state) == "/connections?link=linked"
    client.delete(f"/api/accounts/{accounts(client).accounts[1].id}", headers=ORIGIN)
    fake.grants[code] = grant   # Discord would redeem the code again; only the state stands in the way
    assert back(client, code=code, state=state) == "/connections?link=failed"
    assert discord_owner(db_url, fake.user.id) == 0


@pytest.mark.parametrize("query", [{}, {"state": "never-issued", "code": "x"}])
def test_an_unknown_or_missing_state_links_nothing(client: TestClient, db_url: str, query: dict[str, str]) -> None:
    assert back(client, **query) == "/connections?link=failed"
    assert scalar(db_url, "SELECT count(*) FROM accounts WHERE system = 'discord'") == 0


def test_a_callback_with_no_session_links_nothing(client: TestClient, fake: FakeDiscord, db_url: str) -> None:
    code, state = start(client, fake)
    client.cookies.clear()
    assert back(client, code=code, state=state) == "/connections?link=failed"
    assert discord_owner(db_url, fake.user.id) == 0


def test_declining_at_discord_is_cancelled_and_other_errors_failed(client: TestClient, fake: FakeDiscord) -> None:
    _, state = start(client, fake)
    assert back(client, error="access_denied", state=state) == "/connections?link=cancelled"
    _, state = start(client, fake)
    assert back(client, error="server_error", state=state) == "/connections?link=failed"


def test_a_refused_code_fails_and_discord_down_is_unavailable(client: TestClient, fake: FakeDiscord,
                                                              db_url: str) -> None:
    code, state = start(client, fake)
    fake.refuse = True
    assert back(client, code=code, state=state) == "/connections?link=failed"
    fake.refuse, fake.down = False, True
    assert client.post("/api/accounts/discord/link", headers=ORIGIN).status_code == 503
    assert scalar(db_url, "SELECT count(*) FROM link_pending") == 0


def test_only_ones_own_discord_account_can_be_unlinked(client: TestClient, home: Home, db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        sams = admin.add_account(conn, home.sam, "discord", "111")
    for account_id in (sams, home.alana_signin_account):
        refused = client.delete(f"/api/accounts/{account_id}", headers=ORIGIN)
        assert refused.status_code == 404
    assert scalar(db_url, "SELECT count(*) FROM accounts") == 3


@pytest.mark.parametrize("headers", [{"origin": "https://evil.test"}, {"sec-fetch-site": "cross-site"}])
def test_a_forged_write_is_403_and_changes_nothing(client: TestClient, fake: FakeDiscord, home: Home, db_url: str,
                                                   headers: dict[str, str]) -> None:
    code, state = start(client, fake)
    back(client, code=code, state=state)
    linked = accounts(client).accounts[1].id
    assert client.post("/api/accounts/discord/link", headers=headers).status_code == 403
    assert client.delete(f"/api/accounts/{linked}", headers=headers).status_code == 403
    assert discord_owner(db_url, fake.user.id) == home.alana
    assert scalar(db_url, "SELECT count(*) FROM link_pending") == 0


def test_signed_out_the_routes_are_401(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/accounts").status_code == 401
    assert client.post("/api/accounts/discord/link", headers=ORIGIN).status_code == 401


def test_nothing_secret_or_personal_is_logged(client: TestClient, fake: FakeDiscord, home: Home,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    code, state = start(client, fake)
    back(client, code=code, state=state)
    out = capsys.readouterr().out
    assert f"event=link.ok reason=ok person={home.alana} discord={sub_prefix(fake.user.id)}" in out
    assert not [m for m in (code, state, home.alana_token, fake.user.id, "zqHANDLE", "Alana") if m in out]


def test_unconfigured_linking_is_503_and_the_list_says_so(db_url: str, home: Home) -> None:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        as_(c, home.alana_token)
        assert accounts(c).discord_linking is False
        response = c.post("/api/accounts/discord/link", headers=ORIGIN)
        assert response.status_code == 503
        assert ErrorResponse.model_validate(response.json()).code == "unavailable"
        assert scalar(db_url, "SELECT count(*) FROM link_pending") == 0
