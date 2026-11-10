"""A person's press of Run (`POST /api/benches/{id}/runs`) through the real app over a real database: the run's output
comes back and the bench read back shows it as the piece's `last_run`; the kinds say which languages can run; a note is
refused `not_runnable` (409) and a stale version `stale_base`; a language not offered or a blank piece is 422 with
nothing logged; another person's bench is 404."""

from collections.abc import Generator

import pytest
from bench_run_support import Box
from ashley import services
from ashley.api.bench_run_models import RunApplied
from ashley.api.workshop_models import BenchDetail, CommandRefused, WorkshopKinds
from ashley.runs.sandbox import Sandbox
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from respond_support import ALANA, SAM, Fakes, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

CODE = {"type": "add", "kind": "code", "title": "sum", "body": "print(1+2)", "size": "medium"}
NOTE = {"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"}


@pytest.fixture
def box(signed_in: As) -> Generator[Box]:
    made = Box()
    services.register(Sandbox, made)
    yield made
    services.unregister(Sandbox)


def ran(client: TestClient, bench: int, piece: int, version: int = 1,
        language: str = "python") -> tuple[int, dict[str, object]]:
    response = client.post(f"/api/benches/{bench}/runs", json={"piece_id": piece, "base_version": version,
                                                                "run_language": language})
    return response.status_code, response.json()


def test_a_run_comes_back_with_its_output_and_the_bench_shows_it_on_the_piece(signed_in: As, box: Box) -> None:
    client = signed_in(ALANA)
    kinds = WorkshopKinds.model_validate(client.get("/api/workshop/kinds").json())
    assert kinds.run_languages == ["python"] and kinds.run_max_chars > 0
    bench = opened(client)
    command(client, bench.id, CODE)
    status, body = ran(client, bench.id, 1)
    assert status == 200
    got = RunApplied.model_validate(body)
    assert (got.seq, got.piece_id, got.run_output.run_outcome, got.run_output.stdout) == (2, 1, "ran", "3\n")
    detail = BenchDetail.model_validate(client.get(f"/api/benches/{bench.id}").json())
    last = detail.pieces[0].last_run
    assert last is not None and last.run_id == got.run_id and last.piece_version == 1
    assert last.run_output is not None and last.run_output.files == {"state.txt": "1"}
    assert detail.recent[-1].type == "run" and detail.undo_next == 1
    assert box.jobs[0].script == "print(1+2)"


def test_refusals_are_409_and_what_cannot_run_is_422_with_nothing_logged(signed_in: As, box: Box) -> None:
    client = signed_in(ALANA)
    bench = opened(client)
    command(client, bench.id, NOTE)
    command(client, bench.id, CODE)
    status, body = ran(client, bench.id, 1)
    assert status == 409 and CommandRefused.model_validate(body).reason == "not_runnable"
    status, body = ran(client, bench.id, 2, version=4)
    assert status == 409 and CommandRefused.model_validate(body).reason == "stale_base"
    before = len(BenchDetail.model_validate(client.get(f"/api/benches/{bench.id}").json()).recent)
    status, body = ran(client, bench.id, 2, language="cobol")
    assert status == 422 and body["code"] == "refused"
    after = BenchDetail.model_validate(client.get(f"/api/benches/{bench.id}").json())
    assert len(after.recent) == before and box.jobs == []
    assert all(p.last_run is None for p in after.pieces)


def test_another_persons_bench_is_404(signed_in: As, box: Box) -> None:
    bench = opened(signed_in(ALANA))
    command(signed_in(ALANA), bench.id, CODE)
    status, _ = ran(signed_in(SAM), bench.id, 1)
    assert status == 404 and box.jobs == []


def test_with_no_sandbox_no_language_is_offered(signed_in: As, wired: Fakes) -> None:
    kinds = WorkshopKinds.model_validate(signed_in(ALANA).get("/api/workshop/kinds").json())
    assert kinds.run_languages == []
