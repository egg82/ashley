"""The language on a code run: recorded as given, carried to the sandbox, and a sandbox that does not run it leaves a
failed record with nothing run. Migration 0065: the table allows both languages and no other."""

import json
from pathlib import Path

import psycopg
import pytest
from ashley import services
from ashley.channels.history_runs import block
from ashley.channels.limits import Limits
from ashley.runs.model import Language, Output
from ashley.runs.once import run_once
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from contract.conversations_support import scalar
from sandbox_languages_support import CAD, Rig, World, config, container, python_only, rig, run, world
from sandbox_support import Script, envelope_line

OPENAPI = Path(__file__).resolve().parents[2] / "openapi.json"
LANGUAGES: list[Language] = ["python", "build123d"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_run_is_recorded_in_its_language(db_url: str, language: Language) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new(language))
            started = await w.runs.get(w.home, run_id)
            assert started is not None and started.language == language
            await w.runs.finish(run_id, Output("ran", 0, "x", "", False, {}, ()))
            listed = await w.runs.in_conversation(w.home, w.conversation)
            assert [(r.id, r.language) for r in listed] == [(run_id, language)]
            assert str(scalar(db_url, "SELECT language FROM code_runs WHERE id = %s", (run_id,))) == language

    run(scenario())


def wire(w: World, tmp_path: Path, cad: bool) -> Rig:
    made = rig(tmp_path, Script(log=envelope_line(0, "model")), config() if cad else python_only())
    services.register(Sandbox, made.sandbox)
    services.register(Runs, w.runs)
    return made


def test_a_build123d_run_goes_to_the_cad_pod_and_is_recorded_as_build123d(db_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            kube = wire(w, tmp_path, cad=True).kube
            done = await run_once(w.new("build123d", "box = 1"))
            assert done.reached and done.output.outcome == "ran" and done.output.stdout == "model"
            assert [container(pod)["image"] for pod in kube.created] == [CAD]
            stored = await w.runs.get(w.home, done.run_id)
            assert stored is not None and stored.language == "build123d" and stored.output == done.output
            assert kube.created[0]["metadata"]["name"] == f"run-{done.run_id}"

    run(scenario())


def test_a_build123d_run_with_no_image_is_recorded_as_failed_and_nothing_runs(db_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            kube = wire(w, tmp_path, cad=False).kube
            done = await run_once(w.new("build123d"))
            assert not done.reached
            assert (done.output.outcome, done.output.stdout, done.output.stderr) == ("failed", "", "")
            assert kube.created == []
            stored = await w.runs.get(w.home, done.run_id)
            assert stored is not None and stored.language == "build123d"
            assert stored.output is not None and stored.output.outcome == "failed"

    run(scenario())


def test_the_table_allows_python_and_build123d(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new("python"))
            with psycopg.connect(db_url, autocommit=True) as conn:
                for language in ("build123d", "python"):
                    conn.execute("UPDATE code_runs SET language = %s WHERE id = %s", (language, run_id))

    run(scenario())


@pytest.mark.parametrize("language", ["cobol", "", "Python", "BUILD123D", "build123d "])
def test_the_table_refuses_any_other_language(db_url: str, language: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new("build123d"))
            with psycopg.connect(db_url, autocommit=True) as conn:
                with pytest.raises(psycopg.errors.CheckViolation):
                    conn.execute("UPDATE code_runs SET language = %s WHERE id = %s", (language, run_id))
            kept = await w.runs.get(w.home, run_id)
            assert kept is not None and kept.language == "build123d"

    run(scenario())


def test_a_carried_run_names_its_language(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new("build123d", "box = Box(1, 1, 1)"))
            await w.runs.finish(run_id, Output("ran", 0, "", "", False, {}, ()))
            stored = await w.runs.get(w.home, run_id)
            assert stored is not None
            text = block(stored, Limits(1, 1000, 1, 0, carried_runs=3, run_script_chars=200, run_output_chars=200))
            assert "build123d" in text and "box = Box(1, 1, 1)" in text

    run(scenario())


def test_the_contract_names_both_languages_for_a_run_the_page_shows() -> None:
    schemas = json.loads(OPENAPI.read_text())["components"]["schemas"]
    assert schemas["ChatRun"]["properties"]["language"]["enum"] == ["python", "build123d"]
