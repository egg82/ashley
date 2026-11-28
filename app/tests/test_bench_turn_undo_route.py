"""A person takes back her whole turn over `POST /api/benches/{id}/undo-turn`: every change of the turn goes, or when a
piece changed since none does and the refusals are listed; another person's bench is 404."""

from dataclasses import replace
from typing import Any

from ashley import services
from ashley.workshop.commands import Add, Edit
from ashley.workshop.model import HER, Owner, Text
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from respond_support import ALANA, SAM, Fakes, wired as wired
from test_workshop_routes import ADD, As, command, opened, signed_in as signed_in

OWNER = Owner(ALANA.household_id, ALANA.id)


def hers(client: TestClient, bench: int, *made: Any) -> None:
    """Her accepted commands of turn 5, made through the Workshop as her tools make them."""
    assert client.portal is not None
    for one in made:
        applied = client.portal.call(services.get(Workshop).apply, OWNER, bench, one)
        assert applied.outcome == "accepted"


def her(note: str) -> Add:
    return Add(replace(HER, turn=5), "note", Text(note, ""), "small")


def titles(client: TestClient, bench: int) -> list[str]:
    return [p["title"] for p in client.get(f"/api/benches/{bench}").json()["pieces"]]


def test_the_route_undoes_every_command_of_the_turn(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana).id
    command(alana, bench, ADD)
    hers(alana, bench, her("a"), her("b"), Edit(replace(HER, turn=5), 2, 1, Text("a2", "")))
    response = alana.post(f"/api/benches/{bench}/undo-turn", json={"seq": 2})
    assert (response.status_code, response.json()) == (200, {"undone_seqs": [4, 3, 2]})
    assert titles(alana, bench) == ["parts"]
    detail = alana.get(f"/api/benches/{bench}").json()
    assert [c["seq"] for c in detail["recent"] if c["undone_by"] is not None] == [2, 3, 4]


def test_a_piece_changed_since_refuses_the_whole_turn_and_changes_nothing(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana).id
    hers(alana, bench, her("a"), her("b"))
    edit = {"type": "edit", "piece_id": 1, "base_version": 1, "title": "mine", "body": ""}
    assert command(alana, bench, edit)[0] == 200
    response = alana.post(f"/api/benches/{bench}/undo-turn", json={"seq": 1})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "refused" and body["reason"] == "changed_since"
    assert body["refused"] == [{"seq": 1, "reason": "changed_since"}]
    assert titles(alana, bench) == ["mine", "b"]
    detail = alana.get(f"/api/benches/{bench}").json()
    assert [c["type"] for c in detail["recent"]] == ["add", "add", "edit"]


def test_a_turn_already_undone_is_refused_nothing_to_undo(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana).id
    hers(alana, bench, her("a"))
    assert alana.post(f"/api/benches/{bench}/undo-turn", json={"seq": 1}).status_code == 200
    again = alana.post(f"/api/benches/{bench}/undo-turn", json={"seq": 1})
    assert (again.status_code, again.json()["reason"]) == (409, "nothing_to_undo")


def test_a_person_cannot_undo_a_turn_on_a_bench_they_do_not_own(signed_in: As, wired: Fakes) -> None:
    bench = opened(signed_in(ALANA)).id
    hers(signed_in.client, bench, her("a"))
    response = signed_in(SAM).post(f"/api/benches/{bench}/undo-turn", json={"seq": 1})
    assert (response.status_code, response.json()["code"]) == (404, "not_found")
    assert titles(signed_in(ALANA), bench) == ["a"]
