"""The facts kind over HTTP: the kinds route lists it, a bad body is a 409 `CommandRefused` with reason
`bad_facts` and the bench unchanged, a good one is stored as written, and the route agrees with `decide`."""

from collections.abc import Generator
from typing import Any

import pytest
from ashley.api.workshop_models import BenchDetail, BenchSummary, CommandRefused, WorkshopKinds
from ashley.workshop.decide import Refused
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from facts_kind_blind_support import (GOOD, Rig, build, KIND, MAX_CHARS, body_of, decide_add, good_bodies, refused_as,
                                        with_)
from respond_support import Fakes, wired as wired


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def new_bench(rig: Rig) -> int:
    got = rig.post("/api/benches", {"title": "bench"})
    assert got.status_code == 200
    return int(BenchSummary.model_validate(got.json()).id)


def send(rig: Rig, bench: int, body: dict[str, object]) -> tuple[int, dict[str, Any]]:
    got = rig.post(f"/api/benches/{bench}/commands", body)
    return got.status_code, got.json()


def add(text: str, kind: str = KIND) -> dict[str, object]:
    return {"type": "add", "kind": kind, "title": "m", "body": text, "size": "small"}


def edit(piece_id: int, version: int, text: str) -> dict[str, object]:
    return {"type": "edit", "piece_id": piece_id, "base_version": version, "title": "m", "body": text}


def detail(rig: Rig, bench: int) -> BenchDetail:
    got = rig.get(f"/api/benches/{bench}")
    assert got.status_code == 200
    return BenchDetail.model_validate(got.json())


def test_the_kinds_route_lists_facts_as_a_stored_kind_with_the_rules_limit(rig: Rig) -> None:
    kinds = {k.name: k for k in WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json()).kinds}
    got = kinds[KIND]
    assert (got.family, got.format, got.max_chars) == ("stored", "facts", MAX_CHARS)


def test_a_good_body_is_stored_exactly_as_sent_and_read_back(rig: Rig) -> None:
    b = new_bench(rig)
    body = '{"items":[ {"name":"bore","value":8.0,"unit":"mm","source":"datasheet","tolerance":0.05,"ref":"p.3"} ]}'
    status, raw = send(rig, b, add(body))
    assert status == 200 and raw["piece_id"] == 1
    (piece,) = detail(rig, b).pieces
    assert (piece.kind, piece.body) == (KIND, body)


def test_an_empty_body_is_accepted(rig: Rig) -> None:
    assert send(rig, new_bench(rig), add(""))[0] == 200


def test_a_bad_add_is_a_409_refused_bad_facts_and_the_bench_is_unchanged(rig: Rig) -> None:
    b = new_bench(rig)
    status, raw = send(rig, b, add("not facts"))
    refused = CommandRefused.model_validate(raw)
    assert (status, refused.code, refused.reason, refused.seq) == (409, "refused", "bad_facts", 1)
    after = detail(rig, b)
    assert after.pieces == [] and [(r.seq, r.outcome) for r in after.recent] == [(1, "bad_facts")]


def test_a_bad_edit_is_a_409_and_the_piece_keeps_its_body_and_version(rig: Rig) -> None:
    b = new_bench(rig)
    good = body_of([GOOD])
    send(rig, b, add(good))
    status, raw = send(rig, b, edit(1, 1, body_of([GOOD, GOOD])))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "bad_facts"
    (piece,) = detail(rig, b).pieces
    assert (piece.body, piece.piece_version) == (good, 1)


def test_a_good_edit_is_accepted_and_undo_restores_the_earlier_body(rig: Rig) -> None:
    b = new_bench(rig)
    first = body_of([GOOD])
    send(rig, b, add(first))
    assert send(rig, b, edit(1, 1, body_of([with_(value=3)])))[0] == 200
    assert send(rig, b, {"type": "undo", "seq": 2})[0] == 200
    assert detail(rig, b).pieces[0].body == first


def test_the_same_bad_body_is_accepted_for_a_note(rig: Rig) -> None:
    assert send(rig, new_bench(rig), add("not facts", kind="note"))[0] == 200


def test_an_over_long_body_is_refused_too_long_before_bad_facts(rig: Rig) -> None:
    status, raw = send(rig, new_bench(rig), add("x" * (MAX_CHARS + 1)))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "too_long"


@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(body=st.one_of(good_bodies, st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"), max_size=30), st.sampled_from(["", "{}", "[]", '{"items": [{}]}'])))
def test_the_route_and_decide_agree_on_every_body(rig: Rig, body: str) -> None:
    expected = decide_add(body)
    status, raw = send(rig, new_bench(rig), add(body))
    assert status == (409 if isinstance(expected, Refused) else 200)
    if status == 409:
        assert CommandRefused.model_validate(raw).reason == refused_as(expected) == "bad_facts"
