"""Contract 15 at the routes: a screen bench is on no person's list and every bench route answers 404 for its id, whoever
asks, while a control bench of the same person answers as before."""

import json
from pathlib import Path
from typing import Any

import pytest
from sb_rig import HALL, Rig, ORIGIN
from sb_support import benches_of

OPENAPI = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())
SCREEN_KINDS = {"clock", "home", "conversation", "controls"}


def with_screen(app: Rig) -> tuple[int, int, int]:
    """A bench of Alana's, the id of the screen bench of a tablet whose controls Alana has just set, and the tablet."""
    made = app.client.post("/api/benches", json={"title": "Plan"}, headers=ORIGIN)
    assert made.status_code == 200, made.text
    device, _ = app.tablet()
    assert app.put_controls(device, 0, HALL).status_code == 200
    [screen] = benches_of(app.url, device)
    return int(made.json()["id"]), screen, device


def bench_gets() -> list[str]:
    found = [p for p, methods in OPENAPI["paths"].items() if p.startswith("/api/benches/{bench_id}") and "get" in methods]
    assert len(found) >= 3, "the contract declares the bench reads"
    return found


def filled(path: str, bench_id: int) -> str:
    out = path.replace("{bench_id}", str(bench_id))
    while "{" in out:
        out = out[:out.index("{")] + "1" + out[out.index("}") + 1:]
    return out


def test_k15_the_lists_hold_the_persons_own_bench_and_never_the_screens(app: Rig) -> None:
    bench, screen, _ = with_screen(app)
    for who in ("alana", "sam"):
        app.as_(who)
        for path in ("/api/benches", "/api/benches/closed"):
            got = app.client.get(path)
            assert got.status_code == 200
            ids = [b["id"] for b in got.json()["benches"]]
            assert screen not in ids and (bench in ids) == (who == "alana" and path == "/api/benches")


def test_k15_every_bench_read_of_the_screens_id_is_404_for_everyone(app: Rig) -> None:
    bench, screen, _ = with_screen(app)
    for who in ("alana", "sam", "kim"):
        app.as_(who)
        for path in bench_gets():
            got = app.client.get(filled(path, screen))
            assert got.status_code == 404, (who, path, got.text)
    app.as_("alana")
    assert app.client.get(f"/api/benches/{bench}").status_code == 200


def test_k15_the_bench_writes_of_the_screens_id_are_404_and_change_nothing(app: Rig) -> None:
    _, screen, device = with_screen(app)
    before = app.controls(device)
    add: dict[str, Any] = {"type": "add", "kind": "note", "title": "a", "body": "", "size": "small"}
    for path, body in ((f"/api/benches/{screen}/commands", add), (f"/api/benches/{screen}/close", None),
                       (f"/api/benches/{screen}/reopen", None), (f"/api/benches/{screen}/messages", {"text": "hi"})):
        got = app.client.post(path, json=body, headers=ORIGIN)
        assert got.status_code == 404, (path, got.text)
    assert app.controls(device) == before


@pytest.mark.parametrize("who", ["alana", "sam"])
def test_k15_the_kinds_route_offers_no_screen_kind_to_a_bench(app: Rig, who: str) -> None:
    app.as_(who)
    got = app.client.get("/api/workshop/kinds")
    assert got.status_code == 200
    assert not SCREEN_KINDS & {k["name"] for k in got.json()["kinds"]} and "note" in {k["name"] for k in got.json()["kinds"]}
