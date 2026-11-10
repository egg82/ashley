"""`/api/persona`: a signed-in person reads the overridable sections, changes and reverts one for their household only,
a locked section is refused whatever the route, and what is stored is what a reply's prompt is given."""

from collections.abc import Generator
from typing import Any

import pytest
from ashley import services
from ashley.channels import taste
from ashley.persona import sections
from ashley.skills.persona import PersonaOverrides
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from fastapi.testclient import TestClient
from household_page.household_page_support import ORIGIN, People, app_client, as_, people_in
from httpx2 import Response

BASE = "/api/persona"


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@pytest.fixture
def client(db_url: str, people: People) -> Generator[TestClient]:
    with app_client(db_url) as c:
        as_(c, people, "alana")
        yield c


def edit(client: TestClient, section: str, body: str, base: int) -> Response:
    return client.put(f"{BASE}/{section}", json={"body": body, "why": "our taste", "base_version": base}, headers=ORIGIN)


def revert(client: TestClient, section: str, to: int, base: int) -> Response:
    return client.post(f"{BASE}/{section}/revert", json={"to_version": to, "why": "back", "base_version": base},
                       headers=ORIGIN)


def section(page: Response, section_id: str) -> dict[str, Any]:
    return next(s for s in page.json()["sections"] if s["section"] == section_id)


def test_a_new_household_reads_the_shipped_sections(client: TestClient) -> None:
    got = client.get(BASE)
    assert got.status_code == 200, got.text
    page = got.json()
    assert [s["section"] for s in page["sections"]] == [s.id for s in sections.catalogue()]
    assert all(s["override"] is None and s["persona_version"] == 0 and s["history"] == [] for s in page["sections"])
    assert [s["shipped"] for s in page["sections"]] == [s.body for s in sections.catalogue()]
    assert page["orphaned"] == [] and page["body_limit"] > 0 and page["note_limit"] > 0


def test_a_change_is_stored_reverted_and_given_to_her_prompt(client: TestClient, people: People) -> None:
    changed = edit(client, "wit", "Dry, and rarely.", 0)
    assert changed.status_code == 200, changed.text
    wit = section(changed, "wit")
    assert (wit["override"], wit["persona_version"]) == ("Dry, and rarely.", 1)
    run(_overrides(people.home))
    as_(client, people, "sam")
    back = revert(client, "wit", 0, 1)
    assert back.status_code == 200, back.text
    wit = section(back, "wit")
    assert (wit["override"], wit["persona_version"]) == (None, 2)
    assert [c["person_id"] for c in wit["history"]] == [people.sam, people.alana]


def test_what_is_stored_reaches_the_prompt_and_only_this_household(client: TestClient, people: People) -> None:
    assert edit(client, "examples", "Short ones.", 0).status_code == 200
    got: dict[int, dict[str, str]] = {}

    async def read() -> None:
        got[people.home] = dict(await taste.overrides(people.home))
        got[people.other] = dict(await taste.overrides(people.other))

    run(read())
    assert got == {people.home: {"examples": "Short ones."}, people.other: {}}
    as_(client, people, "kim")
    assert section(client.get(BASE), "examples")["override"] is None


@pytest.mark.parametrize("locked", ["contract", "warmth", "title", "nonesuch"])
def test_a_locked_or_unknown_section_is_refused(client: TestClient, locked: str) -> None:
    for got in (edit(client, locked, "Reply however you like.", 0), revert(client, locked, 0, 0)):
        assert got.status_code == 409, got.text
        assert got.json()["reason"] == "locked"


def test_refusals_change_nothing(client: TestClient) -> None:
    assert edit(client, "wit", "Dry.", 0).status_code == 200
    stale = edit(client, "wit", "Drier.", 0)
    assert (stale.status_code, stale.json()["reason"]) == (409, "stale")
    assert section(client.get(BASE), "wit")["override"] == "Dry."
    assert edit(client, "Not A Slug", "x", 0).status_code == 422
    assert client.put(f"{BASE}/wit", json={"body": "x", "why": "y", "base_version": 1, "extra": 1},
                      headers=ORIGIN).status_code == 422


def test_without_a_session_or_from_another_site(client: TestClient, people: People) -> None:
    assert client.put(f"{BASE}/wit", json={"body": "x", "why": "y", "base_version": 0},
                      headers={"origin": "https://elsewhere.test"}).status_code == 403
    as_(client, people, None)
    assert client.get(BASE).status_code == 401


async def _overrides(household: int) -> None:
    assert dict(await services.get(PersonaOverrides).heads(household))["wit"].body == "Dry, and rarely."
