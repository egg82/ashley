"""`GET /api/trust` and `PUT /api/trust` through the real app: each kind served with what is in force and why a row is
locked, a choice stored under a revision for the signed-in person only, a locked row never loosened, refusals in the
words the route declares with nothing stored, and the store unreadable as `TrustUnavailable`."""

import asyncio
from typing import Any

import psycopg
import pytest
from ashley.api.trust_models import TrustRefused, TrustSettings
from ashley.people import admin
from ashley.trust.postgres import PostgresTrust
from ashley.trust.trust import TrustUnavailable
from contract.contract_support import down_database, unreachable_conninfo
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from oauth_home_support import ORIGIN, Home, as_, client as client, google as google, home as home

URL = "/api/trust"


def put(client: TestClient, revision: int, rows: list[dict[str, Any]], headers: dict[str, str] | None = ORIGIN):
    return client.put(URL, json={"revision": revision, "picks": rows}, headers=headers)


def read(client: TestClient) -> TrustSettings:
    got = client.get(URL)
    assert got.status_code == 200, got.text
    return TrustSettings.model_validate(got.json())


def values(body: TrustSettings) -> dict[str, tuple[str, str | None]]:
    return {r.kind: (r.value, r.locked) for r in body.rows}


def stored(url: str) -> list[tuple[int, int, str, str]]:
    with psycopg.connect(url) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT household_id, person_id, kind, value FROM trust_settings ORDER BY person_id, kind").fetchall()]


def logged(url: str) -> list[tuple[int, str, str | None, str | None]]:
    with psycopg.connect(url) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT person_id, kind, before, after FROM trust_settings_log ORDER BY id").fetchall()]


def test_a_person_who_set_nothing_sees_each_kind_in_force_and_the_locked_rows_with_why(client: TestClient) -> None:
    body = read(client)
    assert body.revision == 0 and body.updated_at is None
    assert values(body) == {"house_removals": ("offer", "irreversible"), "house_setup": ("act", None),
                            "reminder_cancels": ("offer", None), "reminders": ("act", None),
                            "list_removals": ("offer", None), "lists": ("act", None), "messages": ("offer", None),
                            "money": ("offer", "asks"), "printing": ("act", None)}
    assert all(r.label for r in body.rows)


def test_a_choice_is_stored_for_the_person_under_a_revision_and_set_back_deletes_it(client: TestClient, home: Home,
                                                                                    db_url: str) -> None:
    wrote = put(client, 0, [{"kind": "lists", "value": "offer"}, {"kind": "reminders", "value": "act"}])
    assert wrote.status_code == 200, wrote.text
    body = TrustSettings.model_validate(wrote.json())
    assert body.revision == 1 and body.updated_at is not None and values(body)["lists"] == ("offer", None)
    assert values(read(client))["lists"] == ("offer", None)
    assert stored(db_url) == [(home.household, home.alana, "lists", "offer")], "an act equal to unset is not stored"
    back = put(client, 1, [])
    assert back.status_code == 200 and TrustSettings.model_validate(back.json()).revision == 2
    assert stored(db_url) == [] and values(read(client))["lists"] == ("act", None)
    assert logged(db_url) == [(home.alana, "lists", None, "offer"), (home.alana, "lists", "offer", None)]


def test_a_stale_revision_is_409_and_stores_nothing(client: TestClient, db_url: str) -> None:
    assert put(client, 0, [{"kind": "lists", "value": "offer"}]).status_code == 200
    stale = put(client, 0, [{"kind": "messages", "value": "offer"}])
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    assert [r[2] for r in stored(db_url)] == ["lists"]


def test_a_locked_row_put_to_act_is_refused_and_stays_offer(client: TestClient, db_url: str) -> None:
    for kind in ("money", "house_removals"):
        got = put(client, 0, [{"kind": "lists", "value": "offer"}, {"kind": kind, "value": "act"}])
        assert got.status_code == 422, got.text
        assert TrustRefused.model_validate(got.json()).model_dump(exclude={"detail"}) == {"kind": kind, "reason": "locked"}
    assert stored(db_url) == [] and read(client).revision == 0
    assert values(read(client))["money"] == ("offer", "asks")
    assert put(client, 0, [{"kind": "money", "value": "offer"}]).status_code == 200, "offer on a locked row is no change"
    assert stored(db_url) == []


def test_a_kind_that_is_not_one_is_refused_and_stores_nothing(client: TestClient, db_url: str) -> None:
    got = put(client, 0, [{"kind": "purchases", "value": "act"}])
    assert got.status_code == 422 and got.json()["reason"] == "unknown_kind"
    assert client.put(URL, json={"revision": 0, "picks": [{"kind": "lists", "value": "maybe"}]},
                      headers=ORIGIN).status_code == 422
    assert stored(db_url) == []


def test_a_write_from_another_site_or_with_no_session_is_refused(client: TestClient, db_url: str) -> None:
    assert put(client, 0, [{"kind": "lists", "value": "offer"}], headers={"origin": "https://elsewhere.test"}).status_code == 403
    client.cookies.clear()
    assert put(client, 0, [{"kind": "lists", "value": "offer"}]).status_code == 401
    assert client.get(URL).status_code == 401
    assert stored(db_url) == []


def test_a_person_reads_and_writes_only_their_own_rows(client: TestClient, home: Home, db_url: str) -> None:
    assert put(client, 0, [{"kind": "lists", "value": "offer"}]).status_code == 200
    as_(client, home.sam_token)
    assert values(read(client))["lists"] == ("act", None) and read(client).revision == 0
    assert put(client, 0, [{"kind": "printing", "value": "offer"}]).status_code == 200
    assert stored(db_url) == [(home.household, home.alana, "lists", "offer"),
                              (home.household, home.sam, "printing", "offer")]
    as_(client, home.alana_token)
    assert values(read(client))["printing"] == ("act", None)


def test_choices_saved_before_the_defaults_changed_still_win_and_an_act_against_one_is_stored(
        client: TestClient, home: Home, db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("INSERT INTO trust_revisions (household_id, person_id, version) VALUES (%s, %s, 2)",
                     (home.household, home.alana))
        for kind in ("lists", "messages", "reminders"):
            conn.execute("INSERT INTO trust_settings (household_id, person_id, kind, value) VALUES (%s, %s, %s, 'offer')",
                         (home.household, home.alana, kind))
    saved = values(read(client))
    assert (saved["lists"], saved["messages"], saved["reminders"]) == (("offer", None),) * 3
    assert (saved["printing"], saved["list_removals"]) == (("act", None), ("offer", None)), "unsaved kinds take defaults"
    wrote = put(client, 2, [{"kind": "messages", "value": "act"}, {"kind": "list_removals", "value": "act"},
                            {"kind": "printing", "value": "offer"}])
    assert wrote.status_code == 200, wrote.text
    assert stored(db_url) == [(home.household, home.alana, "list_removals", "act"),
                              (home.household, home.alana, "messages", "act"),
                              (home.household, home.alana, "printing", "offer")]
    after = values(read(client))
    assert (after["messages"], after["list_removals"], after["printing"]) == (("act", None), ("act", None),
                                                                             ("offer", None))


def test_another_households_rows_are_neither_shown_nor_touched(client: TestClient, home: Home, db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        other = admin.add_household(conn, "next door", "UTC")
        them = admin.add_person(conn, other, "Kai")
        conn.execute("INSERT INTO trust_revisions (household_id, person_id, version) VALUES (%s, %s, 3)", (other, them))
        conn.execute("INSERT INTO trust_settings (household_id, person_id, kind, value) VALUES (%s, %s, 'lists', 'offer')",
                     (other, them))
    body = read(client)
    assert body.revision == 0 and values(body)["lists"] == ("act", None)
    assert put(client, 0, []).status_code == 200
    assert stored(db_url) == [(other, them, "lists", "offer")]


def test_the_store_out_of_reach_reads_as_unavailable() -> None:
    async def go() -> None:
        with pytest.raises(TrustUnavailable):
            await PostgresTrust(down_database(unreachable_conninfo())).stored(1, 1)

    asyncio.run(asyncio.wait_for(go(), 10))
