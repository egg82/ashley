"""`POST /api/benches/{id}/runs` through the real app: the run's output comes back, the bench read back shows it as the
piece's `last_run`, the kinds say which languages run, and the refusals are the stated statuses with nothing recorded."""

import json
from collections.abc import Generator, Mapping
from pathlib import Path

import pytest
from ashley import services
from ashley.api.bench_run_models import RunApplied
from ashley.api.models import ErrorResponse
from ashley.api.workshop_models import BenchDetail, BenchSummary, CommandRefused, WorkshopKinds
from ashley.live.events import BenchChanged
from ashley.runs.model import Output
from ashley.runs.sandbox import Sandbox
from brb_route_support import Reply, Rig, build
from brb_support import Box, out
from contract.conversations_support import scalar
from respond_support import Fakes, wired as wired

SHIPPED = Path(__file__).resolve().parents[2] / "ashley" / "runs" / "runs.json"
CODE = {"type": "add", "kind": "code", "title": "sum", "body": "print(1+2)", "size": "medium"}
NOTE = {"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"}


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        services.register(Sandbox, made.box)
        yield made


def bench_with(rig: Rig, *commands: Mapping[str, object]) -> int:
    bench = BenchSummary.model_validate(rig.post("/api/benches", {"title": "b"}).json).id
    for body in commands:
        assert rig.post(f"/api/benches/{bench}/commands", body).status == 200
    return bench


def go(rig: Rig, bench: int, piece: int = 1, version: int = 1, language: str = "python") -> Reply:
    return rig.post(f"/api/benches/{bench}/runs", {"piece_id": piece, "base_version": version, "run_language": language})


def detail(rig: Rig, bench: int) -> BenchDetail:
    got = rig.get(f"/api/benches/{bench}")
    assert got.status == 200
    return BenchDetail.model_validate(got.json)


def code_runs(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM code_runs"))


def test_the_kinds_say_which_languages_run_and_how_long_a_script_may_be(rig: Rig) -> None:
    got = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json)
    assert got.run_languages == ["python"]
    assert got.run_max_chars == json.loads(SHIPPED.read_text())["max_script_chars"]


def test_with_a_sandbox_that_runs_nothing_no_language_is_offered(rig: Rig) -> None:
    services.register(Sandbox, Box(offered=()))
    assert WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json).run_languages == []


def test_a_run_comes_back_with_its_output(rig: Rig) -> None:
    bench = bench_with(rig, CODE)
    got = go(rig, bench)
    assert got.status == 200
    done = RunApplied.model_validate(got.json)
    assert (done.seq, done.piece_id) == (2, 1)
    o = done.run_output
    assert (o.run_outcome, o.exit_code, o.stdout, o.stderr, o.output_cut, o.files, o.files_left_out) == (
        "ran", 0, "OUT-A", "ERR-A", False, {"state.txt": "S1"}, [])
    assert [(j.language, j.script) for j in rig.box.jobs] == [("python", "print(1+2)")]
    ran = detail(rig, bench).recent[-1]
    assert (ran.type, ran.author, ran.person_id, ran.piece_id) == ("run", "person", rig.people["alana"].id, 1)


def test_what_was_cut_and_what_was_left_out_are_shown(rig: Rig) -> None:
    rig.box.outputs = [Output("timed_out", None, "so far", "", True, {}, ("big.bin",))]
    bench = bench_with(rig, CODE)
    o = RunApplied.model_validate(go(rig, bench).json).run_output
    assert (o.run_outcome, o.exit_code, o.output_cut, o.files_left_out, o.stdout) == (
        "timed_out", None, True, ["big.bin"], "so far")
    shown = detail(rig, bench).pieces[0].last_run
    assert shown is not None and shown.run_output == o


def test_the_bench_shows_the_run_as_the_pieces_last_run_and_a_never_run_piece_shows_none(rig: Rig) -> None:
    bench = bench_with(rig, CODE, CODE)
    assert [p.last_run for p in detail(rig, bench).pieces] == [None, None]
    done = RunApplied.model_validate(go(rig, bench, 2).json)
    first, second = detail(rig, bench).pieces
    assert first.last_run is None and second.last_run is not None
    last = second.last_run
    assert (last.run_id, last.piece_version, last.finished_at is not None) == (done.run_id, 1, True)
    assert last.run_output == done.run_output


def test_the_latest_run_replaces_the_one_before_on_the_piece(rig: Rig) -> None:
    rig.box.outputs = [out("ran", stdout="one"), out("ran", stdout="two")]
    bench = bench_with(rig, CODE)
    go(rig, bench)
    second = RunApplied.model_validate(go(rig, bench).json)
    shown = detail(rig, bench).pieces[0].last_run
    assert shown is not None and shown.run_id == second.run_id and shown.run_output is not None
    assert shown.run_output.stdout == "two"


def test_the_last_run_names_the_version_it_ran(rig: Rig) -> None:
    bench = bench_with(rig, CODE)
    rig.post(f"/api/benches/{bench}/commands", {"type": "edit", "piece_id": 1, "base_version": 1, "title": "t", "body": "print(2)"})
    go(rig, bench, 1, 2)
    shown = detail(rig, bench).pieces[0]
    assert shown.last_run is not None and shown.last_run.piece_version == shown.piece_version == 2


def test_a_run_changes_no_piece_and_undo_walks_over_it(rig: Rig) -> None:
    bench = bench_with(rig, CODE)
    before = detail(rig, bench)
    done = RunApplied.model_validate(go(rig, bench).json)
    after = detail(rig, bench)
    assert after.undo_next == 1
    assert [(p.piece_version, p.changed_by, p.body, p.placement) for p in after.pieces] == [
        (p.piece_version, p.changed_by, p.body, p.placement) for p in before.pieces]
    assert [(c.type, c.outcome) for c in after.recent][-1] == ("run", "accepted")
    got = rig.post(f"/api/benches/{bench}/commands", {"type": "undo", "seq": done.seq})
    assert got.status == 409 and CommandRefused.model_validate(got.json).reason == "nothing_to_undo"


def test_the_next_run_starts_with_the_files_the_last_one_left(rig: Rig) -> None:
    rig.box.outputs = [out("ran", {"f": "1"}), out("timed_out", {"junk": "x"}), out("ran")]
    bench = bench_with(rig, CODE)
    for _ in range(3):
        go(rig, bench)
    assert [dict(j.files) for j in rig.box.jobs] == [{}, {"f": "1"}, {"f": "1"}]


def test_the_owners_screens_are_told_the_bench_changed(rig: Rig) -> None:
    bench = bench_with(rig, CODE)
    before = len([e for e in rig.heard.events if isinstance(e, BenchChanged)])
    go(rig, bench)
    assert len([e for e in rig.heard.events if isinstance(e, BenchChanged)]) >= before + 2


# --- refusals ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("setup", "piece", "version", "reason"), [
    ([NOTE], 1, 1, "not_runnable"), ([CODE], 1, 4, "stale_base"), ([CODE], 7, 1, "no_such_piece")])
def test_a_refused_run_is_409_with_its_reason_and_nothing_runs(rig: Rig, db_url: str, setup: list[Mapping[str, object]],
                                                               piece: int, version: int, reason: str) -> None:
    bench = bench_with(rig, *setup)
    got = go(rig, bench, piece, version)
    assert got.status == 409
    body = CommandRefused.model_validate(got.json)
    assert (body.code, body.reason, body.seq) == ("refused", reason, len(setup) + 1)
    assert rig.box.jobs == [] and code_runs(db_url) == 0
    assert detail(rig, bench).recent[-1].outcome == reason


def test_a_language_the_sandbox_does_not_run_is_422_and_nothing_is_logged(rig: Rig, db_url: str) -> None:
    bench = bench_with(rig, CODE)
    assert go(rig, bench, language="cobol").status == 422
    assert len(detail(rig, bench).recent) == 1 and rig.box.jobs == [] and code_runs(db_url) == 0


def test_a_blank_piece_is_422_and_nothing_is_logged(rig: Rig, db_url: str) -> None:
    bench = bench_with(rig, {**CODE, "body": "  \n "})
    assert go(rig, bench).status == 422
    assert len(detail(rig, bench).recent) == 1 and rig.box.jobs == [] and code_runs(db_url) == 0


def test_a_piece_longer_than_the_sandbox_takes_is_422_and_one_as_long_is_run(rig: Rig, db_url: str) -> None:
    longest = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json).run_max_chars
    bench = bench_with(rig, {**CODE, "body": "x" * (longest + 1)})
    assert go(rig, bench).status == 422 and len(detail(rig, bench).recent) == 1 and code_runs(db_url) == 0
    exact = bench_with(rig, {**CODE, "body": "x" * longest})
    assert go(rig, exact).status == 200 and code_runs(db_url) == 1


@pytest.mark.parametrize("body", [{}, {"piece_id": 1, "base_version": 1}, {"piece_id": "a", "base_version": 1, "run_language": "python"},
                                  {"piece_id": 1, "base_version": 1, "run_language": "python", "x": 1},
                                  {"piece_id": 1, "base_version": 1, "run_language": ""}])
def test_a_malformed_request_is_422(rig: Rig, body: dict[str, object], db_url: str) -> None:
    bench = bench_with(rig, CODE)
    assert rig.post(f"/api/benches/{bench}/runs", body).status == 422 and code_runs(db_url) == 0


def test_another_persons_bench_is_404_and_nothing_runs(rig: Rig, db_url: str) -> None:
    bench = bench_with(rig, CODE)
    for name in ("sam", "zed"):
        rig.as_(name)
        got = go(rig, bench)
        assert got.status == 404 and ErrorResponse.model_validate(got.json).code == "not_found"
    assert rig.box.jobs == [] and code_runs(db_url) == 0


def test_a_bench_that_does_not_exist_is_404(rig: Rig) -> None:
    assert go(rig, 999).status == 404


def test_signed_out_is_401_and_a_write_from_another_site_is_403(db_url: str, wired: Fakes) -> None:
    out_rig = build(db_url, wired, signed_in=False)
    with out_rig.client as client:
        body = {"piece_id": 1, "base_version": 1, "run_language": "python"}
        assert client.post("/api/benches/1/runs", json=body).status_code == 401
        assert client.post("/api/benches/1/runs", json=body, headers={"origin": "https://evil.test"}).status_code == 403
    assert out_rig.box.jobs == []
