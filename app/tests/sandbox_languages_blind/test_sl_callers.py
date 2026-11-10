"""What callers see of the languages: her loose `run_code` stays Python, the bench's Run and her `bench_run` take any
language the Sandbox runs and refuse the rest before anything is recorded, and the kinds say which languages run."""

from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import services
from ashley.api.bench_run_models import RunApplied
from ashley.api.person import person_signed_in
from ashley.api.workshop_models import BenchSummary, WorkshopKinds
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Person
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.run_code import RunCodeTools, offered
from ashley.tools.tools import Tools
from contract.conversations_support import household, person, scalar
from fastapi.testclient import TestClient
from respond_support import Fakes, wired as wired
from sandbox_languages_support import CAD, Recording, Rig, config, container, python_only, rig, run, world
from sandbox_support import Script, envelope_line

PUBLIC = "https://ashley.test"
CODE = {"type": "add", "kind": "code", "title": "cube", "body": "box = 1", "size": "medium"}
def rows(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM code_runs"))


def test_loose_run_code_offers_python_even_when_the_sandbox_runs_more() -> None:
    services.register(Sandbox, Recording())
    assert offered() == ("python",)


def test_loose_run_code_offers_nothing_when_the_sandbox_runs_only_build123d() -> None:
    services.register(Sandbox, Recording(offers=("build123d",)))
    assert offered() == ()


def test_run_code_refuses_build123d_and_records_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            box = Recording()
            services.register(Sandbox, box)
            services.register(Runs, w.runs)
            tools = RunCodeTools(w.home, w.conversation, w.turn)
            result = await tools.call(ToolCall("c-1", "run_code", {"language": "build123d", "script": "box = 1"}))
            assert result.is_error and box.jobs == [] and rows(db_url) == 0
            ok = await tools.call(ToolCall("c-2", "run_code", {"language": "python", "script": "print(1)"}))
            assert not ok.is_error and [j.language for j in box.jobs] == ["python"]

    run(scenario())


@pytest.fixture
def client(db_url: str, wired: Fakes) -> Generator[TestClient]:
    home = household(db_url, "one")
    alana = Person(person(db_url, home, "Alana"), home, "Alana")
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, alana)
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as made:
        services.register(Live, Live.null())
        services.register(Conversations, wired.conversations)
        services.register(InFlight, InFlight.null())
        services.register(Inference, wired.inference)
        services.register(Tools, wired.tools)
        yield made


def new_bench(client: TestClient) -> int:
    bench = BenchSummary.model_validate(client.post("/api/benches", json={"title": "b"}).json()).id
    assert client.post(f"/api/benches/{bench}/commands", json=CODE).status_code == 200
    return bench


def press_run(client: TestClient, bench: int, language: str) -> int:
    body = {"piece_id": 1, "base_version": 1, "run_language": language}
    return client.post(f"/api/benches/{bench}/runs", json=body).status_code


def kinds(client: TestClient) -> list[str]:
    return WorkshopKinds.model_validate(client.get("/api/workshop/kinds").json()).run_languages


def test_the_kinds_list_build123d_when_the_sandbox_runs_it(client: TestClient) -> None:
    services.register(Sandbox, Recording())
    assert kinds(client) == ["python", "build123d"]


def test_the_press_of_run_in_build123d_runs_the_piece_and_records_the_language(client: TestClient, db_url: str) -> None:
    box = Recording()
    services.register(Sandbox, box)
    bench = new_bench(client)
    got = client.post(f"/api/benches/{bench}/runs", json={"piece_id": 1, "base_version": 1, "run_language": "build123d"})
    assert got.status_code == 200
    assert RunApplied.model_validate(got.json()).run_output.stdout == "OUT-SL"
    assert [(j.language, j.script) for j in box.jobs] == [("build123d", "box = 1")]
    assert str(scalar(db_url, "SELECT language FROM code_runs")) == "build123d"


def test_a_sandbox_that_runs_only_python_refuses_build123d_and_records_nothing(client: TestClient, db_url: str) -> None:
    box = Recording(offers=("python",))
    services.register(Sandbox, box)
    bench = new_bench(client)
    assert kinds(client) == ["python"]
    assert press_run(client, bench, "build123d") == 422
    assert box.jobs == [] and rows(db_url) == 0
    assert press_run(client, bench, "python") == 200


def test_a_kubernetes_sandbox_with_no_cad_image_refuses_build123d_and_makes_no_pod(
        client: TestClient, db_url: str, tmp_path: Path) -> None:
    world_ = rig(tmp_path, Script(log=envelope_line(0, "py")), python_only())
    services.register(Sandbox, world_.sandbox)
    bench = new_bench(client)
    assert kinds(client) == ["python"]
    assert press_run(client, bench, "build123d") == 422
    assert world_.kube.created == [] and rows(db_url) == 0


def test_a_kubernetes_sandbox_with_the_cad_image_runs_the_piece_in_it(client: TestClient, db_url: str, tmp_path: Path) -> None:
    world_: Rig = rig(tmp_path, Script(log=envelope_line(0, "solid")), config())
    services.register(Sandbox, world_.sandbox)
    bench = new_bench(client)
    assert kinds(client) == ["python", "build123d"]
    assert press_run(client, bench, "build123d") == 200
    assert [container(pod)["image"] for pod in world_.kube.created] == [CAD]
    assert str(scalar(db_url, "SELECT language FROM code_runs")) == "build123d"
