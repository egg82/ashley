"""The one connection route, `PUT`/`DELETE /api/connections/{kind}`, over the registered kinds: the list serves the
kinds the adapters declare, a name nothing registered is 404, a body carrying the other secret field than the kind's is
refused before any request, and a kind with one address takes none from the body."""

from ashley.api.connection_models import ConnectionRefused, HouseholdConnection
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from money_support import BASE, KEY, FakeSure
from test_connections_routes import ORIGIN, client as client, homes as homes, listed, sure as sure
from connection_routes_support import delete_kind, put_kind


def test_the_list_serves_every_registered_kind_in_order(client: TestClient) -> None:
    kinds = listed(client).offered
    assert [k.name for k in kinds] == ["home_assistant", "sure", "gitlab", "github", "google", "anthropic", "openai",
                                       "gemini", "elevenlabs", "openai_compatible", "wyoming", "searxng", "discord", "files", "esphome"]
    sure_kind = kinds[1]
    assert sure_kind.secret_field == "api_key" and sure_kind.takes_address and sure_kind.holders == ["household"]
    assert [k.takes_address for k in kinds] == [True, True, True, False, False, False, False, False, False, True, True, True, False, True, False]
    assert [k.holders for k in kinds] == [["household"], ["household"], ["person"], ["person"],
                                          ["household", "person"], *[["household"]] * 9]


def test_a_name_no_adapter_registered_is_not_found_to_connect_or_remove(client: TestClient, sure: FakeSure) -> None:
    put = put_kind(client, "bitbucket", json={"base_url": BASE, "token": KEY}, headers=ORIGIN)
    gone = delete_kind(client, "bitbucket", headers=ORIGIN)
    assert put.status_code == 404 and gone.status_code == 404 and sure.seen == []


def test_the_other_secret_field_than_the_kinds_is_refused_before_any_request(client: TestClient, sure: FakeSure) -> None:
    got = put_kind(client, "sure", json={"base_url": BASE, "token": KEY}, headers=ORIGIN)
    assert got.status_code == 422 and got.json()["code"] == "unsupported" and KEY not in got.text
    assert sure.seen == [] and listed(client).connections == []


def test_a_refusal_is_in_the_kinds_own_words(client: TestClient, sure: FakeSure) -> None:
    sure.status = 401
    got = put_kind(client, "sure", json={"base_url": BASE, "api_key": KEY}, headers=ORIGIN)
    refused = ConnectionRefused.model_validate(got.json())
    assert got.status_code == 400 and refused.reason == "key_refused" and "Sure" in refused.detail


def test_a_kind_connects_through_the_one_route(client: TestClient, sure: FakeSure) -> None:
    got = put_kind(client, "sure", json={"base_url": BASE, "api_key": KEY}, headers=ORIGIN)
    made = HouseholdConnection.model_validate(got.json())
    assert got.status_code == 200 and made.kind == "sure" and not made.personal
