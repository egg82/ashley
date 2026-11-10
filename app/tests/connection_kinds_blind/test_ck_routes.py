"""The connections routes through the real app on a real database and the fake services: `GET /api/connections` and
the one `PUT`/`DELETE /api/connections/{kind}` for every registered kind, the typed refusals (`wrong_service` among
them), and the `HouseholdConnection` wire model."""

from datetime import UTC, datetime, timedelta

import pytest
from ashley.api.connection_models import ConnectionKindInfo, ConnectionRefused, ConnectionsResponse, HouseholdConnection
from ashley.api.models import ErrorResponse
from ashley.wiring import CONNECTION_KINDS
from connection_kinds_blind_support import (ADDRESSES, KIND_NAMES, ORIGIN, SECRETS, Fakes, People, age, as_, body_for,
                                            kind_named, rows, stored_at)
from fastapi.testclient import TestClient
from httpx2 import Response
from connection_routes_support import delete_kind, put_kind

ADDRESS_KINDS = [k.name for k in CONNECTION_KINDS if k.fixed_address is None and not k.pinned]
REFUSALS = {"refuse": "key_refused", "down": "unreachable", "html": "wrong_service", "missing": "wrong_service"}


def put(client: TestClient, kind: str, secret: str | None = None, address: str | None = None) -> Response:
    return put_kind(client, kind, json=body_for(kind, secret, address), headers=ORIGIN)


def listing(client: TestClient) -> ConnectionsResponse:
    got = client.get("/api/connections")
    assert got.status_code == 200
    return ConnectionsResponse.model_validate(got.json())


def kinds_listed(client: TestClient) -> list[str]:
    return [c.kind for c in listing(client).connections]


def made(client: TestClient, kind: str) -> HouseholdConnection:
    got = put(client, kind)
    assert got.status_code == 200
    return HouseholdConnection.model_validate(got.json())


# --- the kinds on offer ---------------------------------------------------------------------------------------------


def test_the_listing_offers_every_registered_kind_in_the_registry_order(client: TestClient) -> None:
    got = listing(client)
    assert [o.name for o in got.offered] == [k.name for k in CONNECTION_KINDS]
    assert got.can_connect and got.connections == []


@pytest.mark.parametrize("name", KIND_NAMES)
def test_an_offered_kind_carries_what_its_adapter_declared(client: TestClient, name: str) -> None:
    declared = kind_named(name)
    offered = next(o for o in listing(client).offered if o.name == name)
    assert offered == ConnectionKindInfo(
        name=name, title=declared.title, what=declared.what, blurb=declared.blurb, connected=declared.connected,
        removed=declared.removed, holders=sorted(declared.holders), most=declared.most, takes_address=declared.fixed_address is None,
        address_placeholder=declared.address_placeholder, secret_field=declared.secret_field,
        secret_label=declared.secret_label, secret_noun=declared.secret_noun, has_settings=bool(declared.settings))


def test_the_offer_is_the_same_before_and_after_connecting(client: TestClient) -> None:
    before = listing(client).offered
    made(client, "sure")
    assert listing(client).offered == before


# --- connect, replace, remove: one route for every kind ---------------------------------------------------------------


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_every_kind_connects_lists_and_disconnects_through_the_one_route(client: TestClient, people: People,
                                                                         fakes: Fakes, db_url: str, kind: str) -> None:
    declared = kind_named(kind)
    got = made(client, kind)
    assert got.kind == kind and got.personal is (declared.default_holder == "person")
    assert got.base_url == (declared.fixed_address or ADDRESSES[kind])
    assert got.added_by is not None and got.added_by.id == people.alana
    assert fakes.count(kind) >= 1 and fakes.secrets() == {SECRETS[kind]}
    assert kinds_listed(client) == [kind] and listing(client).connections[0] == got
    assert delete_kind(client, kind, headers=ORIGIN).status_code == 204
    assert kinds_listed(client) == [] and rows(db_url) == 0
    assert delete_kind(client, kind, headers=ORIGIN).status_code == 404


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_the_secret_is_never_on_the_wire_back(client: TestClient, kind: str) -> None:
    for body in (put(client, kind).text, client.get("/api/connections").text):
        assert SECRETS[kind] not in body


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_connecting_again_replaces_the_connection_and_checks_the_new_secret(client: TestClient, fakes: Fakes,
                                                                            db_url: str, kind: str) -> None:
    made(client, kind)
    again = put(client, kind, secret="a-newer-secret-value")
    assert again.status_code == 400 and ConnectionRefused.model_validate(again.json()).reason == "key_refused"
    fakes.accepts[kind].add("a-newer-secret-value")
    assert put(client, kind, secret="a-newer-secret-value").status_code == 200
    assert kinds_listed(client) == [kind] and rows(db_url) == 1


def test_github_is_reached_at_its_one_address_whatever_is_sent(client: TestClient, fakes: Fakes) -> None:
    fixed = kind_named("github").fixed_address
    got = put_kind(client, "github", json={"token": SECRETS["github"], "base_url": "https://evil.test"},
                     headers=ORIGIN)
    assert got.status_code == 200 and HouseholdConnection.model_validate(got.json()).base_url == fixed
    assert fakes.other_hosts == [] and fakes.count("github") >= 1


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_name_nothing_registered_is_404_for_connect_and_remove(client: TestClient, fakes: Fakes, kind: str) -> None:
    body = body_for(kind)
    got = put_kind(client, "jukebox", json=body, headers=ORIGIN)
    assert got.status_code == 404 and ErrorResponse.model_validate(got.json()).code == "not_found"
    assert delete_kind(client, "jukebox", headers=ORIGIN).status_code == 404
    assert fakes.seen == []


# --- refusals ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", list(REFUSALS))
@pytest.mark.parametrize("kind", KIND_NAMES)
def test_each_refusal_is_typed_in_the_kinds_own_words_and_stores_nothing(client: TestClient, fakes: Fakes, db_url: str,
                                                                          kind: str, mode: str) -> None:
    fakes.mode[kind] = mode
    got = put(client, kind)
    assert got.status_code == 400
    refused = ConnectionRefused.model_validate(got.json())
    assert refused.reason == REFUSALS[mode] and refused.detail == kind_named(kind).refusals[refused.reason]
    assert SECRETS[kind] not in got.text
    assert rows(db_url) == 0 and kinds_listed(client) == []


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_refused_replacement_leaves_the_connection_as_it_was(client: TestClient, people: People, fakes: Fakes,
                                                               db_url: str, kind: str) -> None:
    first = made(client, kind)
    aged = age(db_url, people.home, kind, people.alana if kind_named(kind).default_holder == "person" else None)
    fakes.mode[kind] = "refuse"
    assert put(client, kind).status_code == 400
    assert listing(client).connections == [first.model_copy(update={"checked_at": aged})]


@pytest.mark.parametrize("kind", ADDRESS_KINDS)
@pytest.mark.parametrize("typed", ["ftp://x.test", "x.test", "https://", "https://u:p@x.test", "https://x.test/?a=1",
                                   "https://x.test/#f"])
def test_an_address_the_kind_may_not_be_reached_at_is_bad_url_and_asks_nothing(client: TestClient, fakes: Fakes,
                                                                                db_url: str, kind: str,
                                                                                typed: str) -> None:
    got = put(client, kind, address=typed)
    assert got.status_code == 400
    refused = ConnectionRefused.model_validate(got.json())
    assert refused.reason == "bad_url" and refused.detail == kind_named(kind).refusals["bad_url"]
    assert fakes.seen == [] and rows(db_url) == 0


def test_sure_is_https_only_and_home_assistant_may_be_http(client: TestClient, fakes: Fakes) -> None:
    refused = put(client, "sure", address="http://money.test")
    assert refused.status_code == 400 and ConnectionRefused.model_validate(refused.json()).reason == "bad_url"
    assert put(client, "home_assistant", address="http://ha.test:8123").status_code == 200


@pytest.mark.parametrize("kind", ["home_assistant", "gitlab"])
def test_a_token_without_an_address_for_a_kind_that_needs_one_is_bad_url(client: TestClient, fakes: Fakes,
                                                                          kind: str) -> None:
    got = put_kind(client, kind, json={"token": SECRETS[kind]}, headers=ORIGIN)
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "bad_url"
    assert fakes.seen == []


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_the_other_secret_field_than_the_kinds_is_422_unsupported(client: TestClient, fakes: Fakes, db_url: str,
                                                                    kind: str) -> None:
    other = "token" if kind_named(kind).secret_field == "api_key" else "api_key"
    body = {other: SECRETS[kind], "base_url": ADDRESSES.get(kind, "https://api.github.com")}
    got = put_kind(client, kind, json=body, headers=ORIGIN)
    assert got.status_code == 422 and ErrorResponse.model_validate(got.json()).code == "unsupported"
    assert fakes.seen == [] and rows(db_url) == 0 and SECRETS[kind] not in got.text


# --- personal and household connections ---------------------------------------------------------------------------------


def test_a_code_host_is_the_signed_in_persons_own_and_listed_only_to_them(client: TestClient, people: People,
                                                                          fakes: Fakes) -> None:
    mine = made(client, "gitlab")
    assert mine.personal is True and mine.added_by is not None and mine.added_by.id == people.alana
    as_(client, people, "sam")
    assert kinds_listed(client) == []
    assert delete_kind(client, "gitlab", headers=ORIGIN).status_code == 404
    as_(client, people, "alana")
    assert kinds_listed(client) == ["gitlab"]


def test_two_people_of_a_household_each_hold_their_own_code_host(client: TestClient, people: People,
                                                                 fakes: Fakes, db_url: str) -> None:
    fakes.accepts["gitlab"].add("sams-own-token")
    made(client, "gitlab")
    as_(client, people, "sam")
    assert put(client, "gitlab", secret="sams-own-token").status_code == 200
    assert rows(db_url) == 2 and kinds_listed(client) == ["gitlab"]
    assert delete_kind(client, "gitlab", headers=ORIGIN).status_code == 204
    as_(client, people, "alana")
    assert kinds_listed(client) == ["gitlab"] and rows(db_url) == 1


@pytest.mark.parametrize("kind", ["sure", "home_assistant"])
def test_a_household_connection_is_every_members_to_see_replace_and_remove(client: TestClient, people: People,
                                                                           fakes: Fakes, kind: str) -> None:
    mine = made(client, kind)
    assert mine.personal is False
    as_(client, people, "sam")
    seen = listing(client).connections
    assert [(c.kind, c.personal) for c in seen] == [(kind, False)]
    assert put(client, kind).status_code == 200
    again = listing(client).connections
    assert len(again) == 1 and again[0].added_by is not None and again[0].added_by.id == people.sam
    assert delete_kind(client, kind, headers=ORIGIN).status_code == 204
    as_(client, people, "alana")
    assert kinds_listed(client) == []


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_another_household_sees_and_removes_nothing(client: TestClient, people: People, fakes: Fakes, db_url: str,
                                                    kind: str) -> None:
    made(client, kind)
    as_(client, people, "kim")
    assert kinds_listed(client) == []
    assert delete_kind(client, kind, headers=ORIGIN).status_code == 404
    assert rows(db_url) == 1


def test_each_household_holds_its_own_of_a_kind(client: TestClient, people: People, fakes: Fakes, db_url: str) -> None:
    made(client, "sure")
    as_(client, people, "kim")
    made(client, "sure")
    assert rows(db_url) == 2 and kinds_listed(client) == ["sure"]


# --- checked_at on the wire -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_new_connection_was_checked_just_now(client: TestClient, kind: str) -> None:
    before = datetime.now(UTC)
    got = made(client, kind)
    assert before - timedelta(seconds=5) <= got.checked_at <= datetime.now(UTC) + timedelta(seconds=5)
    assert got.added_at <= got.checked_at + timedelta(seconds=5)


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_the_listing_shows_the_time_the_service_last_answered(client: TestClient, people: People, db_url: str,
                                                              kind: str) -> None:
    made(client, kind)
    aged = age(db_url, people.home, kind, people.alana if kind_named(kind).default_holder == "person" else None)
    shown = listing(client).connections[0]
    assert shown.checked_at == aged and shown.added_at > aged


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_replacing_a_connection_checks_it_again(client: TestClient, people: People, db_url: str, kind: str) -> None:
    made(client, kind)
    who = people.alana if kind_named(kind).default_holder == "person" else None
    aged = age(db_url, people.home, kind, who)
    made(client, kind)
    assert stored_at(db_url, people.home, kind, who) > aged


# --- access ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_signed_out_is_401_everywhere(client: TestClient, kind: str) -> None:
    client.cookies.clear()
    assert client.get("/api/connections").status_code == 401
    assert put(client, kind).status_code == 401
    assert delete_kind(client, kind, headers=ORIGIN).status_code == 401


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_write_from_another_site_is_403_and_changes_nothing(client: TestClient, fakes: Fakes, db_url: str,
                                                               kind: str) -> None:
    made(client, kind)
    other = {"origin": "https://evil.test"}
    assert put_kind(client, kind, json=body_for(kind), headers=other).status_code == 403
    assert delete_kind(client, kind, headers=other).status_code == 403
    assert rows(db_url) == 1


# --- the request's own constraints ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("secret", ["", "has a space", "tab\there", "x" * 501, "nul\x00byte"])
@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_secret_that_is_empty_has_whitespace_is_too_long_or_holds_a_nul_is_422_and_asks_nothing(
        client: TestClient, fakes: Fakes, db_url: str, kind: str, secret: str) -> None:
    got = put(client, kind, secret=secret)
    assert got.status_code == 422 and fakes.seen == [] and rows(db_url) == 0


@pytest.mark.parametrize("address", ["", "https://" + "x" * 500 + ".test", "https://x.test/\x00"])
@pytest.mark.parametrize("kind", ADDRESS_KINDS)
def test_an_address_that_is_empty_too_long_or_holds_a_nul_is_422_and_asks_nothing(
        client: TestClient, fakes: Fakes, db_url: str, kind: str, address: str) -> None:
    got = put(client, kind, address=address)
    assert got.status_code == 422 and fakes.seen == [] and rows(db_url) == 0


@pytest.mark.parametrize("kind", ADDRESS_KINDS)
def test_an_address_typed_with_a_trailing_slash_is_stored_without_it(client: TestClient, kind: str) -> None:
    got = put(client, kind, address=ADDRESSES[kind] + "/")
    assert got.status_code == 200 and HouseholdConnection.model_validate(got.json()).base_url == ADDRESSES[kind]


def test_gitlab_is_https_only(client: TestClient, fakes: Fakes) -> None:
    got = put(client, "gitlab", address="http://gitlab.test")
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "bad_url"
    assert fakes.seen == []
