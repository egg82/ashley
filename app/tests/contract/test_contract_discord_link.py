"""Linking a Discord account, end to end through the real app and database with a fake Discord behind the locator.
Written blind from `ashley.api.models`, `openapi.json`, the `DiscordOAuth` port and `decisions.md`, "A person links
their own Discord account": what the list shows, what starting a link sends and stores, each outcome the callback
redirects to, who may unlink what, and what the logs hold."""

import hashlib
import threading
from collections.abc import Generator
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from ashley.api.models import AccountsResponse, ErrorResponse, LinkStartResponse
from ashley.signin.discord import DiscordUser
from ashley.settings import Settings
from conversations_support import db_url as db_url, migrated_template as migrated_template
from conversations_support import scalar
from discord_link_contract_support import REDIRECT, SITE, Web, landed, query_of, settings, web
from people_support import account
from signin_contract_support import let_time_pass

ALANA = DiscordUser("81234567890123456", "zqalana")
ELLA = DiscordUser("91234567890123456", "zqella")
FORGED = [{"Origin": "https://evil.test"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": SITE, "Content-Type": "text/plain"}]


@pytest.fixture
def w(db_url: str) -> Generator[Web]:
    with web(db_url) as made:
        yield made


def error_code(response: Any) -> str:
    return ErrorResponse.model_validate(response.json()).code


def listed(w: Web, name: str) -> AccountsResponse:
    r = w.accounts(name)
    assert r.status_code == 200, r.text
    return AccountsResponse.model_validate(r.json())


# --- GET /api/accounts ---------------------------------------------------------------------------------------------

def test_the_list_is_the_signed_in_persons_own_accounts_oldest_first(w: Web, db_url: str) -> None:
    account(db_url, w.hh["home"], w.who["A"], "home_assistant", "person.a")
    assert w.link("A", ALANA) == "linked"
    assert w.link("B", ELLA) == "linked"
    got = listed(w, "A")
    assert [a.system for a in got.accounts] == ["authentik", "home_assistant", "discord"]
    assert [a.id for a in got.accounts] == sorted(a.id for a in got.accounts)
    assert got.discord_linking is True
    assert [a.system for a in listed(w, "B").accounts] == ["authentik", "discord"]
    assert [a.system for a in listed(w, "C").accounts] == ["authentik"]


def test_an_account_shows_its_handle_and_whether_it_may_be_unlinked(w: Web, db_url: str) -> None:
    w.link("A", ALANA)
    by_system = {a.system: a for a in listed(w, "A").accounts}
    assert (by_system["discord"].handle, by_system["discord"].unlinkable) == (ALANA.handle, True)
    assert (by_system["authentik"].handle, by_system["authentik"].unlinkable) == (None, False)
    assert by_system["discord"].id == scalar(db_url, "SELECT id FROM accounts WHERE system = 'discord'")


def test_the_list_carries_only_these_fields_and_no_external_id(w: Web) -> None:
    w.link("A", ALANA)
    r = w.accounts("A")
    assert set(r.json()) == {"accounts", "discord_linking"}
    assert all(set(a) == {"id", "system", "handle", "unlinkable"} for a in r.json()["accounts"])
    assert ALANA.id not in r.text and "sub-A" not in r.text


def test_the_list_needs_a_session(w: Web) -> None:
    r = w.accounts(None)
    assert (r.status_code, error_code(r)) == (401, "unauthorized")


def test_unconfigured_the_list_says_so_and_still_lists(db_url: str) -> None:
    with web(db_url, discord=False, fake=False) as w:
        got = listed(w, "A")
        assert got.discord_linking is False and [a.system for a in got.accounts] == ["authentik"]


# --- POST /api/accounts/discord/link -------------------------------------------------------------------------------

def test_starting_a_link_sends_the_browser_to_discord_with_identify_only(w: Web) -> None:
    r = w.start("A")
    assert r.status_code == 201
    url = LinkStartResponse.model_validate(r.json()).authorize_url
    query = query_of(url)
    assert query["scope"] == "identify"
    assert query["redirect_uri"] == REDIRECT
    assert query["state"] and query["code_challenge_method"] == "S256"


def test_the_real_discord_url_asks_for_identify_only_and_returns_here(db_url: str) -> None:
    with web(db_url, fake=False) as w:
        r = w.start("A")
        assert r.status_code == 201, r.text
        url = str(r.json()["authorize_url"])
        query = query_of(url)
        assert (urlsplit(url).scheme, urlsplit(url).netloc) == ("https", "discord.com")
        assert query["scope"] == "identify" and query["redirect_uri"] == REDIRECT
        assert query["client_id"] == "cid" and query["response_type"] == "code" and query["state"]
        assert "csecret" not in url


def test_each_start_has_a_fresh_unguessable_state_bound_to_its_person(w: Web, db_url: str) -> None:
    states = [query_of(w.start(n).json()["authorize_url"])["state"] for n in ("A", "A", "B")]
    assert len(set(states)) == 3 and all(len(s) >= 16 for s in states)
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(b"SELECT state_sha256, person_id, household_id FROM link_pending").fetchall()
    stored = {bytes(r[0]): (r[1], r[2]) for r in rows}
    for state, name in zip(states, ("A", "A", "B"), strict=True):
        assert stored[hashlib.sha256(state.encode()).digest()] == (w.who[name], w.hh["home"])
    assert not any(state in str(rows) for state in states), "a state is stored only as its hash"


def test_starting_a_link_writes_no_account(w: Web) -> None:
    w.start("A")
    assert w.discord_rows() == []


def test_unconfigured_starting_a_link_is_503_and_stores_nothing(db_url: str) -> None:
    with web(db_url, discord=False, fake=False) as w:
        r = w.start("A")
        assert (r.status_code, error_code(r)) == (503, "unavailable")
        assert w.pending() == 0


def test_the_list_follows_whether_the_port_is_configured(w: Web) -> None:
    w.discord.on = False
    assert listed(w, "A").discord_linking is False


@pytest.mark.parametrize("fields", [{"discord_oauth_client_id": "cid"}, {"discord_oauth_client_secret": "csecret"},
                                    {"discord_oauth_client_id": "cid", "discord_oauth_client_secret": "csecret",
                                     "public_url": ""}])
def test_a_half_set_client_is_refused_at_start_up(db_url: str, fields: dict[str, str]) -> None:
    base = {"build_version": "dev", "database_url": db_url, "public_url": SITE} | fields
    with pytest.raises(ValueError):
        Settings(**base)
    assert settings(db_url).discord_oauth_client_id == "cid"


def test_starting_a_link_needs_a_session(w: Web) -> None:
    r = w.start(None)
    assert (r.status_code, error_code(r)) == (401, "unauthorized")
    assert w.pending() == 0


@pytest.mark.parametrize("headers", FORGED)
def test_a_cross_site_or_non_json_start_is_403_and_stores_nothing(w: Web, headers: dict[str, str]) -> None:
    r = w.start("A", headers, content="x" if "Content-Type" in headers else None)
    assert (r.status_code, error_code(r)) == (403, "forbidden")
    assert w.pending() == 0


# --- GET /api/accounts/discord/callback ----------------------------------------------------------------------------

def test_a_callback_links_the_discord_account_to_the_person_who_started_it(w: Web, db_url: str) -> None:
    assert w.link("A", ALANA) == "linked"
    assert w.discord_rows() == [(w.who["A"], ALANA.id)]
    assert scalar(db_url, "SELECT household_id FROM accounts WHERE system = 'discord'") == w.hh["home"]
    assert w.discord.identified, "the code was redeemed with Discord"


def test_the_code_is_redeemed_with_the_verifier_matching_the_challenge_sent(w: Web) -> None:
    """The fake refuses a code whose verifier is not the S256 preimage of the challenge it was started with."""
    assert w.link("A", ALANA) == "linked"
    assert len(w.discord.challenges) == 1


def test_linking_an_account_already_yours_changes_nothing_but_its_handle(w: Web, db_url: str) -> None:
    w.link("A", ALANA)
    first = scalar(db_url, "SELECT id FROM accounts WHERE system = 'discord'")
    assert w.link("A", DiscordUser(ALANA.id, "zqrenamed")) == "linked"
    assert w.discord_rows() == [(w.who["A"], ALANA.id)]
    assert scalar(db_url, "SELECT id FROM accounts WHERE system = 'discord'") == first
    assert [a.handle for a in listed(w, "A").accounts if a.system == "discord"] == ["zqrenamed"]


def test_a_person_may_link_a_second_discord_account(w: Web) -> None:
    assert w.link("A", ALANA) == "linked" and w.link("A", ELLA) == "linked"
    assert sorted(e for _, e in w.discord_rows()) == sorted([ALANA.id, ELLA.id])


def test_cancelling_at_discord_is_cancelled_and_links_nothing(w: Web) -> None:
    _, state = w.begin("A", ALANA)
    assert landed(w.callback("A", state=state, error="access_denied")) == "cancelled"
    assert w.discord_rows() == [] and not w.discord.identified


def test_an_error_beside_a_valid_code_links_nothing(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    assert landed(w.callback("A", state=state, code=code, error="access_denied")) == "cancelled"
    assert w.discord_rows() == [] and not w.discord.identified


def test_an_error_other_than_declining_is_failed_not_cancelled(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    assert landed(w.callback("A", state=state, code=code, error="server_error")) == "failed"
    assert w.discord_rows() == []


def test_an_account_another_person_has_is_taken_and_stays_theirs(w: Web) -> None:
    assert w.link("B", ALANA) == "linked"
    assert w.link("A", ALANA) == "taken"
    assert w.discord_rows() == [(w.who["B"], ALANA.id)]
    assert [a.system for a in listed(w, "A").accounts] == ["authentik"]


def test_an_account_mapped_by_the_admin_to_someone_else_is_taken(w: Web, db_url: str) -> None:
    account(db_url, w.hh["other"], w.who["C"], "discord", ALANA.id)
    assert w.link("A", ALANA) == "taken"
    assert w.discord_rows() == [(w.who["C"], ALANA.id)]


def test_a_callback_by_someone_other_than_who_started_it_writes_nothing(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    assert landed(w.callback("B", code=code, state=state)) == "wrong_person"
    assert w.discord_rows() == []
    assert not any(a.system == "discord" for a in listed(w, "B").accounts + listed(w, "A").accounts)


def test_a_callback_by_a_person_of_another_household_writes_nothing(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    assert landed(w.callback("C", code=code, state=state)) == "wrong_person"
    assert w.discord_rows() == []


def test_discord_unreachable_is_unavailable_and_links_nothing(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    w.discord.mode = "down"
    assert landed(w.callback("A", code=code, state=state)) == "unavailable"
    assert w.discord_rows() == []


def test_a_code_discord_refuses_is_failed_and_links_nothing(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    w.discord.mode = "refused"
    assert landed(w.callback("A", code=code, state=state)) == "failed"
    assert w.discord_rows() == []


def test_an_unknown_state_is_failed(w: Web) -> None:
    code, _ = w.begin("A", ALANA)
    assert landed(w.callback("A", code=code, state="never-issued")) == "failed"
    assert w.discord_rows() == []


@pytest.mark.parametrize("params", [{}, {"code": "x"}, {"state": ""}, {"error": "access_denied"}])
def test_a_callback_with_missing_parts_is_a_redirect_never_a_422(w: Web, params: dict[str, str]) -> None:
    assert landed(w.callback("A", **params)) in ("failed", "cancelled")
    assert w.discord_rows() == []


def test_a_state_works_once(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    assert landed(w.callback("A", code=code, state=state)) == "linked"
    assert landed(w.callback("A", code=code, state=state)) == "failed"


def test_a_replayed_state_does_not_link_again_after_an_unlink(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    w.callback("A", code=code, state=state)
    [(account_id,)] = [(a.id,) for a in listed(w, "A").accounts if a.system == "discord"]
    assert w.unlink("A", account_id).status_code == 204
    w.discord.codes[code] = (ALANA, state)
    assert landed(w.callback("A", code=code, state=state)) == "failed"
    assert w.discord_rows() == []


def test_a_state_is_spent_by_a_failed_attempt_too(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    w.discord.mode = "refused"
    w.callback("A", code=code, state=state)
    w.discord.mode = "ok"
    w.discord.codes[code] = (ALANA, state)
    assert landed(w.callback("A", code=code, state=state)) == "failed"
    assert w.discord_rows() == []


def test_an_expired_state_is_failed(w: Web, db_url: str) -> None:
    code, state = w.begin("A", ALANA)
    let_time_pass(db_url, "link_pending", 24 * 3600)
    assert landed(w.callback("A", code=code, state=state)) == "failed"
    assert w.discord_rows() == []


def test_a_callback_with_no_session_is_failed_and_links_nothing(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    assert landed(w.callback(None, code=code, state=state)) == "failed"
    assert w.discord_rows() == []


def test_a_sign_in_state_does_not_complete_a_link(w: Web) -> None:
    code, _ = w.begin("A", ALANA)
    started = w.client.get("/api/auth/signin")
    other = query_of(started.headers["location"])["state"]
    assert landed(w.callback("A", code=code, state=other)) == "failed"
    assert w.discord_rows() == []


def test_the_callback_needs_no_origin_but_a_session(w: Web) -> None:
    code, state = w.begin("A", ALANA)
    r = w.call("A", "GET", "/api/accounts/discord/callback", {"Sec-Fetch-Site": "cross-site"},
               params={"code": code, "state": state})
    assert landed(r) == "linked"


def test_unconfigured_the_callback_still_redirects_and_links_nothing(db_url: str) -> None:
    with web(db_url, discord=False, fake=False) as w:
        assert landed(w.callback("A", code="c", state="s")) in ("unavailable", "failed")
        assert w.discord_rows() == []


@pytest.mark.parametrize("round_", [0, 1])
def test_a_race_for_one_discord_account_has_one_winner(db_url: str, round_: int) -> None:
    user = DiscordUser(f"7{round_}00000000000001", "zqracer")
    with web(db_url) as w:
        pairs = {n: w.begin(n, user) for n in ("A", "B")}
        landings: dict[str, str] = {}
        gate = threading.Barrier(2)

        def go(name: str) -> None:
            gate.wait()
            code, state = pairs[name]
            landings[name] = landed(w.call(name, "GET", "/api/accounts/discord/callback",
                                           params={"code": code, "state": state}))

        threads = [threading.Thread(target=go, args=(n,)) for n in pairs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(landings.values()) == ["linked", "taken"], landings
        [(owner, external)] = w.discord_rows()
        assert external == user.id and landings[{w.who["A"]: "A", w.who["B"]: "B"}[owner]] == "linked"
