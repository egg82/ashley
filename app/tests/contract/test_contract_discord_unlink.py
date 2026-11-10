"""Unlinking a Discord account and what the link flow logs, through the real app and database with a fake Discord
behind the locator. Written blind from `ashley.api.models`, `openapi.json` and `decisions.md`, "A person links their own
Discord account": a person unlinks only their own Discord accounts, and the logs hold ids and hashed prefixes, never a
Discord id, code, state, handle or token."""

from collections.abc import Generator
from typing import Any

import pytest
from ashley.api.models import AccountsResponse, ErrorResponse
from ashley.signin.discord import DiscordUser
from conversations_support import db_url as db_url, migrated_template as migrated_template
from conversations_support import scalar
from discord_link_contract_support import SITE, Web, query_of, web
from people_support import account

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


# --- DELETE /api/accounts/{id} -------------------------------------------------------------------------------------

def discord_id_of(w: Web, name: str) -> int:
    [found] = [a.id for a in listed(w, name).accounts if a.system == "discord"]
    return found


def test_a_person_unlinks_their_own_discord_account(w: Web) -> None:
    w.link("A", ALANA)
    assert w.unlink("A", discord_id_of(w, "A")).status_code == 204
    assert w.discord_rows() == []
    assert [a.system for a in listed(w, "A").accounts] == ["authentik"]


def test_unlinking_removes_only_that_account(w: Web) -> None:
    w.link("A", ALANA)
    w.link("A", ELLA)
    gone = [a.id for a in listed(w, "A").accounts if a.system == "discord"][0]
    assert w.unlink("A", gone).status_code == 204
    assert len(w.discord_rows()) == 1 and len(listed(w, "A").accounts) == 2


def test_unlinking_twice_is_404_the_second_time(w: Web) -> None:
    w.link("A", ALANA)
    mine = discord_id_of(w, "A")
    assert w.unlink("A", mine).status_code == 204
    r = w.unlink("A", mine)
    assert (r.status_code, error_code(r)) == (404, "not_found")


def test_someone_elses_discord_account_is_404_and_stays(w: Web) -> None:
    w.link("A", ALANA)
    theirs = discord_id_of(w, "A")
    for stranger in ("B", "C"):
        r = w.unlink(stranger, theirs)
        assert (r.status_code, error_code(r)) == (404, "not_found")
    assert w.discord_rows() == [(w.who["A"], ALANA.id)]


def test_an_authentik_account_cannot_be_unlinked_here(w: Web, db_url: str) -> None:
    mine = scalar(db_url, "SELECT id FROM accounts WHERE system = 'authentik' AND person_id = %s", (w.who["A"],))
    r = w.unlink("A", mine)
    assert (r.status_code, error_code(r)) == (404, "not_found")
    assert [a.system for a in listed(w, "A").accounts] == ["authentik"]
    assert w.accounts("A").status_code == 200, "and the session still works"


def test_no_other_system_can_be_unlinked_here(w: Web, db_url: str) -> None:
    ha = account(db_url, w.hh["home"], w.who["A"], "home_assistant", "person.a")
    r = w.unlink("A", ha)
    assert r.status_code == 404
    assert "home_assistant" in [a.system for a in listed(w, "A").accounts]


def test_a_missing_account_is_404(w: Web) -> None:
    r = w.unlink("A", 999999)
    assert (r.status_code, error_code(r)) == (404, "not_found")


def test_unlinking_needs_a_session(w: Web) -> None:
    w.link("A", ALANA)
    r = w.unlink(None, discord_id_of(w, "A"))
    assert (r.status_code, error_code(r)) == (401, "unauthorized")
    assert len(w.discord_rows()) == 1


@pytest.mark.parametrize("headers", FORGED)
def test_a_cross_site_unlink_is_403_and_unlinks_nothing(w: Web, headers: dict[str, str]) -> None:
    w.link("A", ALANA)
    r = w.unlink("A", discord_id_of(w, "A"), headers)
    assert (r.status_code, error_code(r)) == (403, "forbidden")
    assert len(w.discord_rows()) == 1


def test_an_unlinked_account_can_be_linked_by_another_person(w: Web) -> None:
    w.link("A", ALANA)
    w.unlink("A", discord_id_of(w, "A"))
    assert w.link("B", ALANA) == "linked"
    assert w.discord_rows() == [(w.who["B"], ALANA.id)]


# --- logs ----------------------------------------------------------------------------------------------------------

def test_the_logs_carry_no_raw_discord_id_code_state_handle_or_token(w: Web, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    started = w.start("A")
    state = query_of(started.json()["authorize_url"])["state"]
    code, _ = w.discord.approve(started.json()["authorize_url"], ALANA)
    verifier = scalar(w.url, "SELECT verifier FROM link_pending")
    w.callback("A", code=code, state=state)
    other_code, other_state = w.begin("B", ALANA)
    w.callback("B", code=other_code, state=other_state)
    cancelled = w.begin("B", ELLA)
    w.callback("B", state=cancelled[1], error="access_denied")
    w.callback("C", code=code, state=state)
    refused_code, refused_state = w.begin("B", ELLA)
    w.discord.mode = "refused"
    w.callback("B", code=refused_code, state=refused_state)
    w.unlink("A", discord_id_of(w, "A"))
    w.unlink("B", 999999)
    out = capsys.readouterr().out
    assert "link" in out, "the flow logged something to look through"
    leaked = [m for m in (ALANA.id, ELLA.id, ALANA.handle, ELLA.handle, code, other_code, refused_code, state, other_state, refused_state, verifier,
                          w.cookies["A"], w.cookies["B"], "sub-A", "csecret") if m in out]
    assert not leaked, f"{len(leaked)} secret or personal values reached the log"
