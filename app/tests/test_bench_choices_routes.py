"""A tap on a choice row's option, through the real app over a real database: it is the person's Edit of the row (a
new value `stated`, her guess `accepted`), logged and undoable as any; a value off the options is 422 and logs nothing;
only the signed-in owner reaches it; the value they chose is recorded shown, so it is not shown back to them."""

import json

from ashley.api.bench_choices import ChoiceSet
from ashley.api.workshop_models import BenchDetail
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from respond_support import ALANA, SAM, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in


def rows(form: str, source: str = "guessed", **cited: object) -> str:
    return json.dumps({"items": [
        {"kind": "choice", "name": "form", "label": "The lanyard", "value": form, "options": ["flat strap", "round cord"],
         "source": source, **cited},
        {"kind": "choice", "name": "colour", "label": "Colour", "value": "red", "source": "guessed"}]})


def with_facts(client: TestClient, body: str) -> int:
    bench = opened(client).id
    added = {"type": "add", "kind": "facts", "title": "Sizes", "body": body, "size": "small"}
    assert command(client, bench, added)[0] == 200
    return bench


def tap(client: TestClient, bench: int, value: str, piece: int = 1, name: str = "form") -> tuple[int, dict[str, object]]:
    got = client.put(f"/api/benches/{bench}/pieces/{piece}/choices/{name}", json={"value": value})
    return got.status_code, got.json()


def row(client: TestClient, bench: int) -> dict[str, object]:
    detail = BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())
    return json.loads(detail.pieces[0].body)["items"][0]


def recent(client: TestClient, bench: int) -> list[tuple[str, str, str]]:
    detail = BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())
    return [(r.type, r.outcome, r.author) for r in detail.recent]


def test_a_new_option_is_the_persons_stated_edit_recorded_shown_and_undoable(signed_in: As) -> None:
    alana = signed_in(ALANA)
    bench = with_facts(alana, rows("flat strap", "seen", piece=4, ref="photo"))
    status, got = tap(alana, bench, "round cord")
    assert status == 200 and ChoiceSet.model_validate(got).seq == 2
    assert row(alana, bench) == {"kind": "choice", "name": "form", "label": "The lanyard", "value": "round cord",
                                 "options": ["flat strap", "round cord"], "source": "stated"}
    assert recent(alana, bench) == [("add", "accepted", "person"), ("edit", "accepted", "person"),
                                    ("surfaced", "accepted", "person")]
    assert command(alana, bench, {"type": "undo", "seq": 2})[0] == 200
    assert row(alana, bench)["value"] == "flat strap"


def test_tapping_her_guess_accepts_it_and_tapping_a_confirmed_value_changes_nothing(signed_in: As) -> None:
    alana = signed_in(ALANA)
    bench = with_facts(alana, rows("flat strap"))
    status, got = tap(alana, bench, "flat strap")
    assert status == 200 and ChoiceSet.model_validate(got).seq == 2 and row(alana, bench)["source"] == "accepted"
    status, got = tap(alana, bench, "flat strap")
    assert status == 200 and ChoiceSet.model_validate(got).seq is None
    assert [t for t, _, _ in recent(alana, bench)] == ["add", "edit", "surfaced"]


def test_a_value_off_the_options_or_on_a_row_with_none_is_422_and_logs_nothing(signed_in: As) -> None:
    alana = signed_in(ALANA)
    bench = with_facts(alana, rows("flat strap"))
    assert tap(alana, bench, "chain")[0] == 422
    assert tap(alana, bench, "blue", name="colour")[0] == 422
    assert tap(alana, bench, "")[0] == 422
    assert [t for t, _, _ in recent(alana, bench)] == ["add"]


def test_no_such_row_piece_or_bench_is_404(signed_in: As) -> None:
    alana = signed_in(ALANA)
    bench = with_facts(alana, rows("flat strap"))
    assert command(alana, bench, {"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"})[0] == 200
    for status, got in (tap(alana, bench, "round cord", name="shape"), tap(alana, bench, "round cord", piece=2),
                        tap(alana, bench, "round cord", piece=9), tap(alana, bench + 1000, "round cord")):
        assert (status, got["code"]) == (404, "not_found")


def test_only_the_signed_in_owner_reaches_it(signed_in: As) -> None:
    alana = signed_in(ALANA)
    bench = with_facts(alana, rows("flat strap"))
    sam = signed_in(SAM)
    assert tap(sam, bench, "round cord") == (404, {"code": "not_found", "detail": "no such bench"})
    signed_in.app.dependency_overrides.clear()
    assert tap(signed_in.client, bench, "round cord")[0] == 401
    alana = signed_in(ALANA)
    assert row(alana, bench)["value"] == "flat strap" and [t for t, _, _ in recent(alana, bench)] == ["add"]

