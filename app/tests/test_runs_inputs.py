"""Binary inputs reach a run by reference. The app signs a short-lived link for each (`input_links`); the pod's init
container (`fetcher`) fetches them into an emptyDir the run container mounts read-only at `inputs/`, and that container
holds no link. A job without inputs makes the pod it always did."""

import asyncio
import base64
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from ashley.files import links
from ashley.runs import fetcher, input_links
from ashley.runs.config import Profile
from ashley.runs.kubernetes import FETCHER, KubernetesSandbox
from ashley.runs.model import InputFile, Job
from ashley.runs.pod_spec import FETCH_LABEL, LABEL, manifest
from ashley.runs.sandbox import SandboxUnavailable
from ashley.settings import Settings
from sandbox_support import CONFIG, PYTHON, Clock, FakeKube, Script

KEY = b"k" * 32
APP = "http://10.0.0.5:8000"
CAD_IMAGE = "registry.test/cad@sha256:" + "c" * 64
CAD = Profile(CAD_IMAGE, 60, 120, "1", "500m", "1Gi", 32, 4096, 1024, 16 * 1024 * 1024)
RUNS = replace(CONFIG, languages={"python": PYTHON, "build123d": CAD})
DATA = {"7.stl": b"solid seven", "8.3mf": b"\x00" * 5000}


def stored(data: bytes) -> InputFile:
    return InputFile(3, hashlib.sha256(data).hexdigest(), len(data))


JOB = Job("run-9", "build123d", "show(1)", inputs={name: stored(data) for name, data in DATA.items()})


def pod_of(job: Job = JOB) -> dict[str, Any]:
    return manifest(job, RUNS, "RUNNER", "gvisor", "FETCHER", input_links.sign(job.inputs, APP, KEY, 2_000_000_000))


def test_a_job_with_inputs_gets_an_init_container_that_fills_a_volume_the_run_mounts_read_only() -> None:
    pod = pod_of()
    spec = pod["spec"]
    (init,), (run,) = spec["initContainers"], spec["containers"]
    assert init["command"][-1] == "FETCHER" and init["volumeMounts"] == [{"name": "inputs", "mountPath": "/inputs"}]
    assert {"name": "inputs", "mountPath": "/work/inputs", "readOnly": True} in run["volumeMounts"]
    assert {"name": "inputs", "emptyDir": {"sizeLimit": "16Mi"}} in spec["volumes"]
    assert pod["metadata"]["labels"] == {LABEL: "true", FETCH_LABEL: "true"}
    assert spec["automountServiceAccountToken"] is False and spec["dnsConfig"] == {"nameservers": ["127.0.0.1"]}
    assert init["securityContext"]["readOnlyRootFilesystem"] and init["securityContext"]["capabilities"] == {"drop": ["ALL"]}


def test_the_run_container_holds_no_link_and_no_bytes() -> None:
    run = pod_of()["spec"]["containers"][0]
    assert not any(APP in str(e["value"]) or "ASHLEY_BLOB" in str(e["name"]) for e in run["env"])
    assert "/api/files/" not in json.dumps(run)


def test_each_input_is_one_link_naming_its_object_valid_until_the_deadline() -> None:
    init = pod_of()["spec"]["initContainers"][0]
    task = json.loads(base64.b64decode(init["env"][0]["value"]))
    assert [f["name"] for f in task["files"]] == sorted(DATA)
    for item in task["files"]:
        assert item["url"].startswith(APP + links.PATH)
        token = item["url"].removeprefix(APP + links.PATH)
        grant = links.check(KEY, token, 1_999_999_999)
        assert grant is not None and (grant.household_id, grant.sha256) == (3, item["sha256"])
        assert links.check(KEY, token, 2_000_000_000) is None and links.check(b"x" * 32, token, 1) is None


def test_a_job_without_inputs_makes_no_init_container_volume_or_label() -> None:
    pod = manifest(Job("run-1", "python", "x"), RUNS, "RUNNER", "gvisor")
    assert "initContainers" not in pod["spec"] and [v["name"] for v in pod["spec"]["volumes"]] == ["work", "out"]
    assert pod["metadata"]["labels"] == {LABEL: "true"}


def test_inputs_and_links_must_name_the_same_files() -> None:
    with pytest.raises(ValueError):
        manifest(JOB, RUNS, "RUNNER", "gvisor", "FETCHER", {"7.stl": APP})


def run_with(tmp_path: Path, job: Job, script: Script | None = None, app_url: str = APP) -> tuple[FakeKube, Any]:
    fake, clock = FakeKube(tmp_path / "token", script or Script()), Clock()
    sandbox = KubernetesSandbox(fake.api(), RUNS, "ashley-sandbox", "gvisor", sleep=clock.sleep, clock=clock,
                                app_url=app_url, link_key=KEY if app_url else b"", wall=lambda: 1000.0)
    try:
        return fake, asyncio.run(sandbox.run(job))
    except SandboxUnavailable as e:
        return fake, e


def test_the_sandbox_signs_links_that_end_with_the_pods_deadline(tmp_path: Path) -> None:
    fake, _ = run_with(tmp_path, JOB)
    task = json.loads(base64.b64decode(fake.created[0]["spec"]["initContainers"][0]["env"][0]["value"]))
    token = task["files"][0]["url"].removeprefix(APP + links.PATH)
    assert links.check(KEY, token, 1000 + CAD.pod_deadline_s - 1) is not None
    assert links.check(KEY, token, 1000 + CAD.pod_deadline_s) is None
    assert fake.created[0]["spec"]["initContainers"][0]["command"][-1] == FETCHER


def test_inputs_without_an_app_address_are_unavailable_and_no_pod_is_made(tmp_path: Path) -> None:
    fake, got = run_with(tmp_path, JOB, app_url="")
    assert isinstance(got, SandboxUnavailable) and fake.created == []


def test_an_input_that_could_not_be_fetched_says_so_instead_of_unknown(tmp_path: Path) -> None:
    _, got = run_with(tmp_path, JOB, Script(phases=["Failed"], log="", log_status=400, init_exit=1))
    assert (got.outcome, got.exit_code) == ("failed", None) and "input" in got.stderr


class Reply(io.BytesIO):
    def __enter__(self) -> "Reply":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def serve(monkeypatch: pytest.MonkeyPatch, bodies: dict[str, bytes]) -> list[str]:
    asked: list[str] = []

    def urlopen(url: str, timeout: int) -> Reply:
        asked.append(url)
        return Reply(bodies[url])

    monkeypatch.setattr(fetcher.urllib.request, "urlopen", urlopen)
    return asked


def task_env(files: list[dict[str, object]]) -> dict[str, str]:
    return {"ASHLEY_FETCH": base64.b64encode(json.dumps({"timeout_s": 5, "files": files}).encode()).decode()}


def item(file: str, data: bytes, url: str = "http://a/x", **over: object) -> dict[str, object]:
    return {"name": file, "url": url, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), **over}


def test_the_fetcher_writes_each_file_read_only_when_size_and_digest_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"http://a/1": DATA["7.stl"], "http://a/2": DATA["8.3mf"]})
    monkeypatch.setattr(fetcher, "INPUTS", tmp_path)
    monkeypatch.setattr(fetcher.os, "environ", task_env([item("7.stl", DATA["7.stl"], "http://a/1"),
                                                       item("8.3mf", DATA["8.3mf"], "http://a/2")]))
    fetcher.main()
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == DATA
    assert all(not (p.stat().st_mode & 0o222) for p in tmp_path.iterdir())


@pytest.mark.parametrize("over", [{"size": 3}, {"sha256": "0" * 64}, {"size": 10_000}, {"name": "../x"}, {"name": "a/b"}])
def test_the_fetcher_fails_the_pod_for_a_file_that_is_not_what_was_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                         over: dict[str, object], capsys: pytest.CaptureFixture[str]) -> None:
    serve(monkeypatch, {"http://a/1": DATA["7.stl"]})
    monkeypatch.setattr(fetcher, "INPUTS", tmp_path)
    monkeypatch.setattr(fetcher.os, "environ", task_env([item("7.stl", DATA["7.stl"], "http://a/1", **over)]))
    with pytest.raises(SystemExit) as stopped:
        fetcher.main()
    assert stopped.value.code == 1 and list(tmp_path.iterdir()) == [] and "http" not in capsys.readouterr().err


SANDBOX = {"database_url": "postgresql://x", "build_version": "t", "sandbox_token_file": "/token", "sandbox_ca_file": "/ca",
           "files_endpoints": "http://nas.test", "files_bucket": "b", "files_access_key": "k", "files_secret_key": "s",
           "files_link_key": "l" * 40}


def test_the_address_inputs_are_fetched_from_is_an_ip_address_and_port_since_the_pod_has_no_resolver() -> None:
    assert Settings(sandbox_app_url="http://10.96.0.12:8080", **SANDBOX).sandbox_app_url == "http://10.96.0.12:8080"
    for bad in ("http://ashley.svc:8080", "https://10.96.0.12:8080", "http://10.96.0.12", "http://10.96.0.12:8080/x"):
        with pytest.raises(ValueError, match="SANDBOX_APP_URL must be"):
            Settings(sandbox_app_url=bad, **SANDBOX)
    with pytest.raises(ValueError, match="SANDBOX_APP_URL needs"):
        Settings(sandbox_app_url="http://10.96.0.12:8080", database_url="postgresql://x", build_version="t")
